import json

texts = [
    '{\n  "score": 50,\n  "summary": "Hello',
    '{\n  "score": 50,\n  "summary": "Hello\nWorld"}',
    '{\n  "score": 50,\n  "summary": "Hello"',
    '{\n  "score": 50,\n  "summary": "'
]

for t in texts:
    try:
        json.loads(t, strict=False)
    except Exception as e:
        print(repr(t))
        print(repr(e))
