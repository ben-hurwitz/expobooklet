const puppeteer = require('puppeteer');
const path      = require('path');
const http      = require('http');
const fs        = require('fs');

function startServer(folder, port) {
  const MIME = {
    '.html': 'text/html',
    '.css':  'text/css',
    '.js':   'application/javascript',
    '.png':  'image/png',
    '.svg':  'image/svg+xml',
  };

  const server = http.createServer((req, res) => {
    const urlPath  = decodeURIComponent(req.url.split('?')[0]);
    const filePath = path.join(folder, urlPath === '/' ? 'booklet.html' : urlPath);
    fs.readFile(filePath, (err, data) => {
      if (err) { res.writeHead(404); res.end('Not found'); return; }
      const mime = MIME[path.extname(filePath).toLowerCase()] || 'application/octet-stream';
      res.writeHead(200, { 'Content-Type': mime });
      res.end(data);
    });
  });

  return new Promise((resolve, reject) => {
    server.on('error', reject);
    server.listen(port, '127.0.0.1', () => resolve(server));
  });
}

(async () => {
  const PORT       = 3179;
  const outputPath = path.resolve(__dirname, 'expo_booklet.pdf');

  console.log('🌐 Starting local file server on port', PORT, '...');
  let server;
  try {
    server = await startServer(__dirname, PORT);
  } catch (e) {
    console.error('❌ Could not start server on port ' + PORT + ': ' + e.message);
    process.exit(1);
  }

  console.log('🚀 Launching headless Chrome...');
  const browser = await puppeteer.launch({
    headless: true,
    args: ['--no-sandbox', '--disable-setuid-sandbox'],
  });

  const page = await browser.newPage();
  await page.setViewport({ width: 1200, height: 900 });

  // ── Pipe browser console to terminal so we can see JS errors ──
  page.on('console', msg => {
    const type = msg.type();
    const text = msg.text();
    if (type === 'error') console.log('  [browser error]', text);
    else if (type === 'warn') console.log('  [browser warn]', text);
    else console.log('  [browser]', text);
  });
  page.on('pageerror', err => console.log('  [page exception]', err.message));
  page.on('requestfailed', req =>
    console.log('  [request failed]', req.url().substring(0, 120), req.failure()?.errorText)
  );

  const url = 'http://127.0.0.1:' + PORT + '/booklet.html';
  console.log('📄 Opening ' + url + ' ...');
  try {
    await page.goto(url, { waitUntil: 'networkidle0', timeout: 60000 });
  } catch (e) {
    // networkidle0 can time out if Google Sheets keeps a connection open — that's OK
    // We'll check for cards separately below
    console.log('  (networkidle0 timed out — continuing anyway, this is normal)');
  }

  console.log('⏳ Waiting up to 45s for cards to render...');
  let timedOut = false;
  try {
    await page.waitForFunction(
      () => document.querySelectorAll('.exhibit-box').length > 0,
      { timeout: 45000, polling: 500 }
    );
  } catch (e) {
    timedOut = true;
  }

  // Dump page state for diagnosis
  const diagnostics = await page.evaluate(() => {
    return {
      title:      document.title,
      cardCount:  document.querySelectorAll('.exhibit-box').length,
      pageCount:  document.querySelectorAll('.page').length,
      loadingText: document.getElementById('loading')?.textContent || '(no #loading element)',
      statusText:  document.getElementById('status')?.textContent || '(no #status element)',
      bodySnippet: document.body.innerHTML.substring(0, 400),
    };
  });

  console.log('\n── Page diagnostics ──────────────────────────────────');
  console.log('  Title:       ', diagnostics.title);
  console.log('  Cards found: ', diagnostics.cardCount);
  console.log('  Pages found: ', diagnostics.pageCount);
  console.log('  #loading:    ', diagnostics.loadingText);
  console.log('  #status:     ', diagnostics.statusText);
  console.log('  Body snippet:', diagnostics.bodySnippet.replace(/\s+/g,' ').substring(0, 300));
  console.log('──────────────────────────────────────────────────────\n');

  if (timedOut || diagnostics.cardCount === 0) {
    console.error('❌ No cards rendered. See diagnostics above.');
    console.error('   Common causes:');
    console.error('   1. Google Sheets not published to web (File → Share → Publish to web → CSV)');
    console.error('   2. The sheet URL has changed');
    console.error('   3. A JS error in booklet.html (check [browser error] lines above)');
    await browser.close();
    server.close();
    process.exit(1);
  }

  await new Promise(r => setTimeout(r, 1500));

  const cardCount = diagnostics.cardCount;
  const pageCount = diagnostics.pageCount;
  console.log('✅ Rendered ' + cardCount + ' exhibits across ' + pageCount + ' pages');

  console.log('🖨  Generating PDF → ' + outputPath);
  await page.pdf({
    path: outputPath,
    format: 'Letter',
    printBackground: true,
    margin: { top: 0, right: 0, bottom: 0, left: 0 },
    preferCSSPageSize: true,
  });

  await browser.close();
  server.close();

  console.log('\n✨ Done!');
  console.log('   📁 ' + outputPath);
  console.log('   ' + pageCount + ' pages · ' + cardCount + ' exhibits');

})().catch(err => {
  console.error('❌ Unexpected error:', err.message);
  process.exit(1);
});