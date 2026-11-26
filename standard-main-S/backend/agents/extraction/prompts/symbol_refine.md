You are verifying ONE candidate symbol on a piping and instrumentation diagram (P&ID).

The image is a tight crop around a detection that an earlier pass reported with LOW confidence.
The crop was enlarged so the symbol is easier to see. The message names the candidate's symbol
type and states the crop size in pixels.

Decide two things.

1. PRESENT — is a real P&ID symbol of that type (or a very close variant of it) actually drawn in
   this crop? Text labels, tag bubbles without a symbol, line crossings, arrowheads, dimension
   marks and hatching are NOT symbols.

2. BBOX — if present, give the tightest box around the symbol's own linework, in pixels of THIS
   crop, with (0,0) at the crop's top-left corner. Include the whole symbol body: valve bowties,
   instrument circles and their inner lines, actuator heads, equipment outlines. Exclude attached
   pipes, leader lines and the tag text next to the symbol.

CONFIDENCE CALIBRATION
- 0.90-1.00: the shape is unambiguous and clearly of the named type.
- 0.70-0.89: clearly a symbol; the type is right or a close variant.
- 0.50-0.69: probably a symbol, partly obscured or cut off by the crop edge.
- below 0.50: you are guessing. Report present=false instead.

Respond with only this JSON object:
{"present": true, "bbox": [x1, y1, x2, y2], "confidence": 0.00}

When there is no such symbol:
{"present": false, "bbox": null, "confidence": 0.00}
where confidence is how sure you are that NO symbol is there.
