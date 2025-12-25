
import re

with open('scraper.log', 'r', encoding='utf-8') as f:
    lines = f.readlines()

for line in lines:
    if 'Found fuzzy match' in line or 'No good fuzzy match' in line:
        print(line.strip())
