#!/usr/bin/env python3
# test_langdetect.py - Test language detection
from langdetect import detect, DetectorFactory
from langdetect.lang_detect_exception import LangDetectException

# Set seed for consistent results
DetectorFactory.seed = 0

# Test queries in different languages
test_queries = [
    "What is OSGeo?",
    "¿Qué es OSGeo?",
    "Qu'est-ce que OSGeo?",
    "Was ist OSGeo?",
    "OSGeo是什么？",
    "are you online?",
    "hi",
    "ok",
    "Tell me about GDAL and how it connects to Frank Warmerdam",
    "Explícame sobre GDAL y cómo se conecta con Frank Warmerdam",
]

print("Language Detection Test")
print("=" * 60)

for query in test_queries:
    try:
        lang = detect(query)
        print(f"{query[:50]:<50} -> {lang}")
    except LangDetectException:
        print(f"{query[:50]:<50} -> UNKNOWN (too short)")

print("=" * 60)