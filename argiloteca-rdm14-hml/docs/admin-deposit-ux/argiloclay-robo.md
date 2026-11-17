# ArgiloClay-Robo

Em 19/10/2026, o bloco Assistente RAG DRX / RAG XRD Wizard foi retirado do comparador, junto com seus atributos de endpoints no template. APIs, índice RAG, parser e motor científico permanecem disponíveis para evolução posterior. O código legado do comparador já possui guardas para a ausência desses elementos e não consulta o RAG sem o painel.

O mascote ArgiloClay-Robo foi criado por geração de imagem, com fundo transparente, nas cores creme, marrom e laranja da Argiloteca/CPAA. O original e o prompt estão em `output/imagegen/argiloclay-robo/`; a imagem otimizada é servida localmente por `argiloteca/static/images/argiloclay-robo-v1.png`.

O acesso fica no canto inferior direito, nas bases públicas, de conta e administração. O botão fica compacto no celular. Seu painel usa popover HTML nativo com rótulos em PT/EN, suporte ao teclado e fechamento por botão, Escape e clique externo. O estilo mantém o popover fechado até ser solicitado, contrariando explicitamente o reset de `section` herdado do Semantic UI. Há espaço ao final do rodapé e da administração para os controles de fim de página não ficarem presos sob o botão.

Esta etapa cria a identidade visual e o acesso à futura interface. O painel informa que o assistente está em preparação e não coleta perguntas nem envia consultas. Nenhum novo endpoint ou permissão foi criado.

Validação: 14 respostas HTTPS reais (sete páginas públicas em dois idiomas), mais templates atuais de administração e depósito renderizados em isolamento. Playwright aprovou 36 cenários (nove superfícies × PT/EN × 320/1440px), com carregamento da imagem, presença única, painel fechado inicialmente, tradução, teclado, fechamento e limites do viewport. Sem exceções JavaScript e sem chamadas ao RAG. O gráfico e os controles de importação/exportação do comparador continuam no DOM; não foi feita nova validação do motor científico nem de uma curva importada. Capturas mobile/desktop inspecionadas. Evidências em `output/playwright/argiloclay-robo/`.
