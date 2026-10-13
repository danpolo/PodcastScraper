"""One-to-one, time-aware occurrence matching for diagnostic evaluation."""
import math
import re
import unicodedata


def _norm(s):
    return re.sub(r'\s+', ' ', re.sub(r'[^\w\s\u0590-\u05ff]', ' ',
                  unicodedata.normalize('NFKC', s or ''))).strip().lower()


def timed_term_recall_strict(tokens, reference, tolerance=1.5):
    """Match each emitted term to at most one verified time-local occurrence.

    Token timestamps are approximations; results remain diagnostic, not
    acoustic proof of correctness.
    """
    surfaces = set(reference.get('technical_terms') or [])
    expected = [o for o in reference.get('verified_occurrences') or []
                if o.get('surface') in surfaces and o.get('review_status') == 'verified']
    if not expected:
        return None
    sequence = []
    timings = []
    for token in tokens or []:
        try:
            start, end = float(token['start']), float(token['end'])
            valid = (math.isfinite(start) and math.isfinite(end)
                     and 0 <= start <= end and end - start <= 6)
        except (KeyError, TypeError, ValueError):
            valid = False
        chunk = unicodedata.normalize('NFKC', str(token.get('text', '')))
        for char in chunk:
            normalized = char.lower() if char.isalnum() or char == '_' else ' '
            if normalized.isspace():
                normalized = ' '
                if sequence and sequence[-1] == ' ':
                    continue
            sequence.append(normalized)
            timings.append((start, end) if valid else None)
        if not valid and sequence and sequence[-1] != ' ':
            sequence.append(' ')
            timings.append(None)
    text = ''.join(sequence)
    emitted = []
    for term in sorted(surfaces):
        phrase = _norm(term)
        if not phrase:
            continue
        pat = re.compile(r'(?<![a-z0-9])' + re.escape(phrase) + r'(?![a-z0-9])')
        for match in pat.finditer(text):
            spans = timings[match.start():match.end()]
            if not spans or any(t is None for t in spans):
                continue
            start = min(t[0] for t in spans)
            end = max(t[1] for t in spans)
            if end - start > 6:
                continue
            emitted.append((term, start, end))
    edges = []
    for i, occ in enumerate(expected):
        a, b = float(occ['start']), float(occ['end'])
        for j, (term, x, y) in enumerate(emitted):
            if term != occ['surface']:
                continue
            if y < a - tolerance or x > b + tolerance:
                continue
            gap = abs((x+y)/2 - (a+b)/2)
            edges.append((gap, i, j))
    edges.sort()
    matched_reference = set()
    matched_emitted = set()
    for _, i, j in edges:
        if i not in matched_reference and j not in matched_emitted:
            matched_reference.add(i)
            matched_emitted.add(j)
    misses = [{'term': o['surface'], 'at_s': round(float(o['start']), 2)}
              for i, o in enumerate(expected) if i not in matched_reference]
    return {'recall': round(len(matched_reference) / len(expected), 4),
            'matched': len(matched_reference), 'total': len(expected),
            'missed': misses, 'unmatched_emissions': len(emitted) - len(matched_emitted),
            'method': 'one_to_one_timed_normalized_surface_matching',
            'diagnostic_only': True}
