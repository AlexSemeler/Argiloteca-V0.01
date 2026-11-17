#!/usr/bin/env python3
"""Isolated V59 extension for a structured admin free/combined search."""
import argparse
import importlib.util
import json
import os
from pathlib import Path


def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


if __name__=='__main__':
    os.umask(0o077)
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root',type=Path,required=True)
    args=parser.parse_args()
    source=Path(__file__).resolve().parents[1]/'argiloteca_custom/argiloteca/openalex'
    adapter=load('openalex_search_adapters',source/'adapters.py')
    search=load('openalex_search_runner',source/'search_extractor.py')
    raise SystemExit(search.run(args.source_root,json.loads(os.environ['ARGILOTECA_OPENALEX_SEARCH']),adapter))
