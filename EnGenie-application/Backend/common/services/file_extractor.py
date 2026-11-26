"""
File Extraction Utilities
Extracts text from various file formats: PDF, DOCX, DOC, TXT, CSV, Images (OCR)
"""

import csv
import io
import logging
from typing import Any

# fitz (PyMuPDF) will be imported lazily inside extract_text_from_pdf if not disabled
from docx import Document  # python-docx for DOCX
from PIL import Image

# Initialize logger first
logger = logging.getLogger(__name__)

IMAGE_MAX_SIDE = 2400
IMAGE_TRANSCRIBE_PROMPT = (
    "Transcribe all text in this image exactly as written, in natural reading order "
    "(top to bottom, left to right; table rows as lines with cells separated by ' | '). "
    "Keep numbers, units, tags and part numbers exactly. Do not describe the image, "
    "summarise or add anything. If there is no text at all, reply NO_TEXT."
)

def extract_text_from_pdf(file_bytes: bytes) -> str:
    """
    Extract text from PDF file, falling back to pypdf if PyMuPDF DLL loading fails.

    Args:
        file_bytes: PDF file as bytes

    Returns:
        Extracted text
    """
    import os
    disable_pymupdf = os.getenv("DISABLE_PYMUPDF", "true").lower() == "true"
    
    fitz_obj = None
    if not disable_pymupdf:
        try:
            import fitz
            fitz_obj = fitz
        except (ImportError, Exception) as e:
            logger.warning(f"Failed to import PyMuPDF (fitz): {e}")

    if fitz_obj is not None:
        try:
            doc = fitz_obj.open(stream=file_bytes, filetype="pdf")
            text_parts = []
            max_pages = min(len(doc), 50)

            for page_num in range(max_pages):
                page = doc[page_num]
                page_text = page.get_text("text")
                if page_text.strip():
                    text_parts.append(f"--- Page {page_num + 1} ---\n{page_text}")

            doc.close()

            extracted_text = "\n\n".join(text_parts)
            logger.info(f"Extracted {len(extracted_text)} characters from PDF via PyMuPDF ({max_pages} pages)")
            return extracted_text

        except Exception as e:
            logger.warning(f"PyMuPDF PDF extraction failed: {e}. Falling back to pypdf...")
    else:
        if disable_pymupdf:
            logger.info("PyMuPDF is disabled via DISABLE_PYMUPDF toggle. Using pypdf directly.")

    # pypdf fallback
    try:
        import pypdf
        reader = pypdf.PdfReader(io.BytesIO(file_bytes))
        text_parts = []
        max_pages = min(len(reader.pages), 50)
        for page_num in range(max_pages):
            page = reader.pages[page_num]
            page_text = page.extract_text()
            if page_text and page_text.strip():
                text_parts.append(f"--- Page {page_num + 1} ---\n{page_text}")

        extracted_text = "\n\n".join(text_parts)
        logger.info(f"Extracted {len(extracted_text)} characters from PDF via pypdf fallback ({max_pages} pages)")
        return extracted_text
    except Exception as e:
        logger.error(f"Failed to extract text from PDF via pypdf fallback: {e}")
        return ""


def extract_text_from_docx(file_bytes: bytes) -> str:
    """
    Extract text from DOCX file

    Args:
        file_bytes: DOCX file as bytes

    Returns:
        Extracted text
    """
    try:
        doc = Document(io.BytesIO(file_bytes))
        text_parts = []

        # Extract paragraphs
        for para in doc.paragraphs:
            if para.text.strip():
                text_parts.append(para.text)

        # Extract tables
        for table in doc.tables:
            for row in table.rows:
                row_text = " | ".join([cell.text.strip() for cell in row.cells])
                if row_text.strip():
                    text_parts.append(row_text)

        extracted_text = "\n".join(text_parts)
        logger.info(f"Extracted {len(extracted_text)} characters from DOCX")
        return extracted_text

    except Exception as e:
        logger.error(f"Failed to extract text from DOCX: {e}")
        return ""


def extract_text_from_image(file_bytes: bytes) -> str:
    """
    Extract text from an image with the vision LLM (the configured provider):
    everything printed or written in it, in reading order.

    Args:
        file_bytes: Image file as bytes

    Returns:
        The transcribed text
    """
    import base64

    try:
        image = Image.open(io.BytesIO(file_bytes))
        if image.mode not in ('RGB', 'L'):
            image = image.convert('RGB')
        # the model reads a page-sized image well; a huge scan only costs tokens
        longest = max(image.size)
        if longest > IMAGE_MAX_SIDE:
            scale = IMAGE_MAX_SIDE / longest
            image = image.resize((max(1, int(image.width * scale)), max(1, int(image.height * scale))))
        buf = io.BytesIO()
        image.save(buf, format='PNG')
    except Exception as e:
        logger.error(f"Failed to open image for text extraction: {e}")
        raise RuntimeError(f"Could not open the image: {e}") from e

    try:
        from adapters.llm_factory import get_provider
        provider = get_provider()
        logger.info("Transcribing image text with the vision LLM...")
        resp = provider.complete_with_image(
            prompt=IMAGE_TRANSCRIBE_PROMPT,
            image_b64=base64.b64encode(buf.getvalue()).decode('utf-8'),
            media_type='image/png',
            max_tokens=4096,
            tier='smart',
        )
        extracted_text = (resp.text or '').strip()
    except Exception as e:
        logger.error(f"Failed to extract text from image with the vision LLM: {e}")
        raise RuntimeError(f"Failed to extract text from image: {e}") from e

    if not extracted_text or extracted_text.upper() == 'NO_TEXT':
        logger.warning("Image transcription found no text")
        raise RuntimeError("No text found in image. The image may be blank, too low quality, or contain only graphics.")
    logger.info(f"Extracted {len(extracted_text)} characters from image via the vision LLM")
    return extracted_text

def extract_text_from_txt(file_bytes: bytes) -> str:
    """
    Extract text from plain text file

    Args:
        file_bytes: Text file as bytes

    Returns:
        Decoded text
    """
    try:
        # Try UTF-8 first
        try:
            text = file_bytes.decode('utf-8')
        except UnicodeDecodeError:
            # Fallback to latin-1
            text = file_bytes.decode('latin-1')

        logger.info(f"Extracted {len(text)} characters from text file")
        return text.strip()

    except Exception as e:
        logger.error(f"Failed to extract text from text file: {e}")
        return ""


def extract_text_from_csv(file_bytes: bytes) -> str:
    """
    Extract text from CSV file

    Args:
        file_bytes: CSV file as bytes

    Returns:
        Text representation of CSV data
    """
    try:
        # Try UTF-8 first, then fallback
        try:
            text_content = file_bytes.decode('utf-8')
        except UnicodeDecodeError:
            try:
                text_content = file_bytes.decode('latin-1')
            except UnicodeDecodeError:
                text_content = file_bytes.decode('cp1252')

        # Parse CSV
        csv_reader = csv.reader(io.StringIO(text_content))
        rows = list(csv_reader)

        if not rows:
            logger.warning("CSV file is empty")
            return ""

        # Extract headers
        headers = rows[0] if rows else []

        # Convert to readable text format for LLM processing
        text_parts = []
        text_parts.append(f"CSV File with {len(rows)} rows and {len(headers)} columns")
        text_parts.append(f"Headers: {', '.join(headers)}")
        text_parts.append("")

        # Add each row as a structured entry
        for i, row in enumerate(rows[1:], start=1):  # Skip header row
            row_data = []
            for j, value in enumerate(row):
                if j < len(headers):
                    header = headers[j]
                    if value.strip():  # Only include non-empty values
                        row_data.append(f"{header}: {value.strip()}")

            if row_data:
                text_parts.append(f"Row {i}: {' | '.join(row_data)}")

        extracted_text = "\n".join(text_parts)
        logger.info(f"Extracted {len(extracted_text)} characters from CSV ({len(rows)} rows)")
        return extracted_text

    except Exception as e:
        logger.error(f"Failed to extract text from CSV file: {e}")
        return ""


def extract_text_from_excel(file_bytes: bytes) -> str:
    """
    Extract text from Excel file (xlsx, xls)

    Args:
        file_bytes: Excel file as bytes

    Returns:
        Text representation of Excel data
    """
    try:
        import openpyxl

        workbook = openpyxl.load_workbook(io.BytesIO(file_bytes), data_only=True)
        text_parts = []

        for sheet_name in workbook.sheetnames:
            sheet = workbook[sheet_name]
            text_parts.append(f"=== Sheet: {sheet_name} ===")

            rows = list(sheet.iter_rows(values_only=True))
            if not rows:
                continue

            headers = [str(cell) if cell else "" for cell in rows[0]]
            text_parts.append(f"Headers: {', '.join(headers)}")

            for i, row in enumerate(rows[1:], start=1):
                row_data = []
                for j, cell in enumerate(row):
                    if cell is not None and j < len(headers):
                        header = headers[j]
                        row_data.append(f"{header}: {cell}")

                if row_data:
                    text_parts.append(f"Row {i}: {' | '.join(row_data)}")

            text_parts.append("")

        extracted_text = "\n".join(text_parts)
        logger.info(f"Extracted {len(extracted_text)} characters from Excel")
        return extracted_text

    except ImportError:
        logger.error("openpyxl not installed - Excel extraction not available")
        return ""
    except Exception as e:
        logger.error(f"Failed to extract text from Excel file: {e}")
        return ""


def extract_text_from_file(file_bytes: bytes, filename: str) -> dict[str, Any]:
    """
    Extract text from uploaded file based on file type

    Args:
        file_bytes: File content as bytes
        filename: Original filename with extension

    Returns:
        Dict with extracted text and metadata
    """
    file_ext = filename.lower().split('.')[-1] if '.' in filename else ''

    logger.info(f"Extracting text from file: {filename} (type: {file_ext})")

    extracted_text = ""
    file_type = ""

    # PDF files
    if file_ext == 'pdf':
        file_type = "PDF"
        extracted_text = extract_text_from_pdf(file_bytes)

    # DOCX files
    elif file_ext == 'docx':
        file_type = "DOCX"
        extracted_text = extract_text_from_docx(file_bytes)

    # DOC files (older Word format - requires conversion or different library)
    elif file_ext == 'doc':
        file_type = "DOC"
        logger.warning("DOC format not fully supported. Please convert to DOCX or PDF.")
        extracted_text = ""

    # Text files
    elif file_ext in ['txt', 'text', 'log']:
        file_type = "TEXT"
        extracted_text = extract_text_from_txt(file_bytes)

    # CSV files
    elif file_ext == 'csv':
        file_type = "CSV"
        extracted_text = extract_text_from_csv(file_bytes)

    # Excel files
    elif file_ext in ['xlsx', 'xls']:
        file_type = "EXCEL"
        extracted_text = extract_text_from_excel(file_bytes)

    # Image files (OCR)
    elif file_ext in ['jpg', 'jpeg', 'png', 'bmp', 'tiff', 'tif']:
        file_type = "IMAGE"
        try:
            extracted_text = extract_text_from_image(file_bytes)
        except RuntimeError as e:
            logger.warning(f"Image OCR failed for {filename}: {e}")
            return {
                "filename": filename,
                "file_type": file_type,
                "extracted_text": "",
                "character_count": 0,
                "success": False,
                "error": str(e)
            }

    else:
        logger.warning(f"Unsupported file type: {file_ext}")
        file_type = "UNSUPPORTED"

    return {
        "filename": filename,
        "file_type": file_type,
        "extracted_text": extracted_text,
        "character_count": len(extracted_text),
        "success": len(extracted_text) > 0
    }
