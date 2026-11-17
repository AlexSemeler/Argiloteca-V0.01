"""Instance UI terminology; never rewrite translation keys, URLs or identifiers."""
from __future__ import annotations
import re

_TERMS = {'community': 'collection', 'communities': 'collections', 'comunidade': 'coleção', 'comunidades': 'coleções', 'subcommunity': 'subcollection', 'subcommunities': 'subcollections', 'subcomunidade': 'subcoleção', 'subcomunidades': 'subcoleções', 'comunitário': 'da coleção', 'comunitária': 'da coleção', 'comunitários': 'das coleções', 'comunitárias': 'das coleções', 'subcomunitário': 'de subcoleção'}
_WORD = re.compile(r'(?<![\w/.-])(subcommunities|subcommunity|subcomunidades|subcomunidade|subcomunitário|comunitários|comunitárias|comunitário|comunitária|communities|community|comunidades|comunidade)(?![\w/-])', re.I)
_PROTECTED = re.compile(r'(https?://[^\s<>"\']+|/[\w./?=&%#-]+|\{\{.*?\}\}|\{[A-Za-z_][A-Za-z0-9_]*\}|%\([^)]+\)[a-z]|<[^>]+>)')

def collection_terms(value):
    """Replace human-facing nouns, preserving grammar case and protected tokens."""
    def replace(match):
        word = match.group()
        result = _TERMS[word.lower()]
        return result.upper() if word.isupper() else result.capitalize() if word[0].isupper() else result
    return ''.join(part if index % 2 else _WORD.sub(replace, part)
                   for index, part in enumerate(_PROTECTED.split(value)))
