import json
from fastapi import Response
from bson import ObjectId


class DateTimeEncoder(json.JSONEncoder):
    def default(self, obj):
        if hasattr(obj, 'isoformat'):
            return obj.isoformat()
        if isinstance(obj, ObjectId):
            return str(obj)
        return super().default(obj)


def JSONResponse(content, status_code=200, headers=None):
    """FastAPI JSON response helper with datetime serialization support."""
    if headers is None:
        headers = {}
    json_bytes = json.dumps(content, cls=DateTimeEncoder).encode('utf-8')
    return Response(
        content=json_bytes,
        status_code=status_code,
        headers=headers,
        media_type='application/json'
    )
