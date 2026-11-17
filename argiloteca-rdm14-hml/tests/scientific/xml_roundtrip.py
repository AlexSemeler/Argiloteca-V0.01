"""Independent XML reader for value comparisons (never calls exporter helpers)."""
from decimal import Decimal
XSI='{http://www.w3.org/2001/XMLSchema-instance}'

def local(element):return element.tag.rsplit('}',1)[-1]

def generic(element):
    kind=element.get('kind')
    if kind=='object':return {n.get('name'):generic(n) for n in element}
    if kind=='array':return [generic(n) for n in element]
    if kind=='null':return None
    if kind=='boolean':return element.text in {'true','1'}
    if kind=='number':return Decimal(element.text)
    return element.text or ''

def typed(element,definition,schemas):
    if element.get(XSI+'nil')=='true':return None
    if '$ref' in definition:definition=schemas[definition['$ref']]
    if element.get('kind'):return generic(element)
    kind=definition.get('type')
    if isinstance(kind,list):kind=next(k for k in kind if k!='null')
    if kind=='object':return {local(n):typed(n,definition['properties'][local(n)],schemas) for n in element}
    if kind=='array':
        item=definition.get('items',{})
        result=[]
        for node in element:
            if 'anyOf' in item:
                branch=node[0]
                result.append(typed(branch,item['anyOf'][0],schemas) if local(branch)=='drx' else generic(branch))
            else:result.append(typed(node,item,schemas))
        return result
    if kind=='boolean':return element.text in {'true','1'}
    if kind in {'number','integer'}:return Decimal(element.text)
    return element.text or ''

def normalize(value):
    if isinstance(value,dict):return {k:normalize(v) for k,v in value.items()}
    if isinstance(value,list):return [normalize(v) for v in value]
    if isinstance(value,float):return Decimal(str(value))
    return value
