async (page) => {
  const id=path=>'science-'+path.map(encodeURIComponent).join('-');
  async function put(path,value){
    const key=id(path),row=page.locator('label[for="'+key+'"]').locator('..');
    await row.locator('select.science-presence').selectOption(value===null?'null':'value');
    if(value===null)return;
    const input=page.locator('[id="'+key+'"]');await input.fill(String(value));
  }
  async function array(field,label){
    const labelNode=page.locator('label[for="'+id(['custom_fields',field])+'"]');
    const details=labelNode.locator('xpath=ancestor::details[1]');
    if(!(await details.evaluate(node=>node.open)))await details.locator('summary').click();
    const row=labelNode.locator('..');
    await row.locator('select.science-presence').selectOption('value');
    await page.getByRole('button',{name:'Add item: '+label,exact:true}).click();
  }
  await put(['metadata','title'],'SYNTHETIC — Playwright scientific form / ação & < >');
  await put(['metadata','publication_date'],'2026-01-01');
  await put(['metadata','creators',0,'person_or_org','family_name'],'Synthetic');
  await put(['metadata','creators',0,'person_or_org','given_name'],'Playwright');
  await array('arg:pesquisas_campo','Field campaigns');
  await put(['custom_fields','arg:pesquisas_campo',0,'campanha_id'],'PW-CAMP-0001');
  await put(['custom_fields','arg:pesquisas_campo',0,'titulo'],'SYNTHETIC — Campanha < & >');
  await array('arg:amostras','Samples');
  await put(['custom_fields','arg:amostras',0,'codigo_amostra'],'0001');
  await put(['custom_fields','arg:amostras',0,'campanha_id'],'PW-CAMP-0001');
  await put(['custom_fields','arg:amostras',0,'latitude'],0);
  await put(['custom_fields','arg:amostras',0,'longitude'],-51.1234567890123);
  await put(['custom_fields','arg:amostras',0,'altitude_m'],null);
  await page.locator('#science-save').click();
  await page.waitForFunction(()=>document.getElementById('science-status').textContent==='Draft saved.');
  const draft=page.url().split('/').pop();await page.reload();
  if(await page.locator('[id="'+id(['custom_fields','arg:amostras',0,'codigo_amostra'])+'"]').inputValue()!=='0001')throw Error('Sample code not preserved');
  if(await page.locator('[id="'+id(['custom_fields','arg:amostras',0,'latitude'])+'"]').inputValue()!=='0')throw Error('Zero lost');
  const presence=page.locator('label[for="'+id(['custom_fields','arg:amostras',0,'altitude_m'])+'"]').locator('..').locator('select.science-presence');
  if(await presence.inputValue()!=='null')throw Error('Null lost');
  return {check:'UI nested create, save and reload preserves 0001, zero, precision, null and Unicode',draft};
}
