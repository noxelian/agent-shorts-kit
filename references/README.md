# Reference images

Place owner-supplied identity and style reference PNG/JPEG files here. Then add
their project-relative paths to `pipeline/production.json`, for example:

```json
"reference_images": [
  "references/identity-sheet.png",
  "references/style-frame-1.png",
  "references/style-frame-2.png"
]
```

Reference images are ignored by git by default because they may contain private
brand assets or media the owner is not allowed to redistribute.

