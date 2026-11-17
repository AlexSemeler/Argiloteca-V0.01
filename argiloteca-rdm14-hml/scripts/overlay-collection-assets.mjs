/** Apply UI terminology to generated JSON translation dictionaries only.
 * Source builds use translations/frontend overrides. This bounded overlay updates
 * an existing deployment without touching vendor sources or application logic.
 */
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import {pathToFileURL} from 'node:url';
const [input, output] = process.argv.slice(2);
if (!input || !output) throw Error('Usage: overlay-collection-assets.mjs INPUT_DIST OUTPUT_DIST');
const parserPath=path.resolve(import.meta.dirname,'../../.tools/i18n-js/node_modules/@babel/parser/lib/index.js');
const {parse}=await import(pathToFileURL(parserPath));
const terms={community:'collection',communities:'collections',comunidade:'coleção',comunidades:'coleções',subcommunity:'subcollection',subcommunities:'subcollections',subcomunidade:'subcoleção',subcomunidades:'subcoleções','comunitário':'da coleção','comunitária':'da coleção','comunitários':'das coleções','comunitárias':'das coleções','subcomunitário':'de subcoleção'};
function replace(value){
 return value.split(/(https?:\/\/[^\s<>"']+|\/[\w./?=&%#-]+|\{\{.*?\}\}|\{[A-Za-z_][A-Za-z0-9_]*\}|%\([^)]+\)[a-z]|<[^>]+>)/g).map((part,index)=>index%2?part:part.replace(/(?<![\w/.-])(subcommunities|subcommunity|subcomunidades|subcomunidade|subcomunitário|comunitários|comunitárias|comunitário|comunitária|communities|community|comunidades|comunidade)(?![\w/-])/gi,word=>{
  const result=terms[word.toLowerCase()];return word===word.toUpperCase()?result.toUpperCase():word[0]===word[0].toUpperCase()?result[0].toUpperCase()+result.slice(1):result;
 })).join('');
}
function walk(node,fn){if(!node||typeof node!=='object')return; if(node.type)fn(node);for(const [key,value] of Object.entries(node)){if(['loc','extra','comments','tokens'].includes(key))continue;if(Array.isArray(value))value.forEach(n=>walk(n,fn));else if(value&&typeof value==='object')walk(value,fn);}}
const mapping=new Map(), reports=[], changed=new Map();
fs.mkdirSync(path.join(output,'js'),{recursive:true});
for(const filename of fs.readdirSync(path.join(input,'js')).filter(f=>f.endsWith('.js')&&!f.startsWith('manifest.'))){
 const source=fs.readFileSync(path.join(input,'js',filename),'utf8');
 if(!source.includes('JSON.parse')||!/(communities|comunidades|community|comunidade)/i.test(source))continue;
 const patches=[];let messages=0;
 walk(parse(source,{sourceType:'unambiguous'}),node=>{
  if(node.type!=='CallExpression'||node.callee.type!=='MemberExpression'||node.callee.object.name!=='JSON'||node.callee.property.name!=='parse'||node.arguments[0]?.type!=='StringLiteral')return;
  const literal=node.arguments[0];let data;
  try{data=JSON.parse(literal.value);}catch{return;}
  if(!data||Array.isArray(data)||typeof data!=='object'||Object.keys(data).length<10||!Object.values(data).every(v=>typeof v==='string'))return;
  let count=0;
  for(const [key,value] of Object.entries(data)){const next=replace(value);if(next!==value){data[key]=next;count++;}}
  if(count){patches.push({start:literal.start,end:literal.end,text:JSON.stringify(JSON.stringify(data))});messages+=count;}
 });
 if(!patches.length)continue;
 let next=source;for(const patch of patches.sort((a,b)=>b.start-a.start))next=next.slice(0,patch.start)+patch.text+next.slice(patch.end);
 next=next.replace(/\n?\/\/# sourceMappingURL=[^\r\n]*/g,'');
 // Parsing again proves that escaping changes cannot corrupt generated code.
 parse(next,{sourceType:'unambiguous'});
 const hash=crypto.createHash('sha256').update(next).digest('hex').slice(0,16);
 const name=filename.replace(/\.[a-f0-9]+\.js$/,'.'+hash+'.js');
 mapping.set(filename,name);changed.set(name,next);reports.push({from:filename,to:name,dictionaries:patches.length,messages});
}
for(const filename of fs.readdirSync(path.join(input,'js')).filter(f=>f.startsWith('manifest.')&&f.endsWith('.js'))){
 let source=fs.readFileSync(path.join(input,'js',filename),'utf8'),next=source;
 for(const [oldName,newName] of mapping){const oldHash=oldName.split('.').at(-2),newHash=newName.split('.').at(-2);next=next.replaceAll('"'+oldHash+'"','"'+newHash+'"');}
 if(next!==source){parse(next,{sourceType:'unambiguous'});const hash=crypto.createHash('sha256').update(next).digest('hex').slice(0,16);const name=filename.replace(/\.[a-f0-9]+\.js$/,'.'+hash+'.js');mapping.set(filename,name);changed.set(name,next);reports.push({from:filename,to:name,runtime:true});}
}
function rename(value){if(typeof value==='string'){for(const [oldName,newName] of mapping)value=value.replaceAll(oldName,newName);return value;}if(Array.isArray(value))return value.map(rename);if(value&&typeof value==='object')return Object.fromEntries(Object.entries(value).map(([k,v])=>[rename(k),rename(v)]));return value;}
const originalManifest=JSON.parse(fs.readFileSync(path.join(input,'manifest.json'),'utf8'));
// Original source maps describe the old literals and must not be advertised for replacements.
for(const name of Object.keys(originalManifest.assets)){if(name.endsWith('.js.map')&&mapping.has(path.basename(name).slice(0,-4)))delete originalManifest.assets[name];}
const manifest=rename(originalManifest);
for(const [name,source] of changed)fs.writeFileSync(path.join(output,'js',name),source);
fs.writeFileSync(path.join(output,'manifest.json'),JSON.stringify(manifest));
fs.writeFileSync(path.join(output,'terminology-report.json'),JSON.stringify(reports,null,2));
console.log(JSON.stringify({files:changed.size,dictionaries:reports.reduce((s,r)=>s+(r.dictionaries||0),0),messages:reports.reduce((s,r)=>s+(r.messages||0),0)}));
