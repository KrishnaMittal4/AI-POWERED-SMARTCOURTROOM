/**
 * Certified Court Order / Judgment Exporter
 * Generates an official judicial decree formatted according to High Court / Supreme Court standards
 * and triggers immediate PDF download / print rendering.
 */

export function exportCertifiedCourtOrder(result, interlocutoryThreads = []) {
  if (!result) return

  const dateStr = new Date().toLocaleDateString('en-IN', {
    day: 'numeric',
    month: 'long',
    year: 'numeric',
  })

  const year = new Date().getFullYear()
  const orderNo = `HC/${year}/LEX-${Math.floor(1000 + Math.random() * 9000)}`

  const petCitations = (result.petitioner.citations || [])
    .map((c) => (typeof c === 'string' ? c : c.case_name || c.source_file))
    .filter(Boolean)
    .join('; ') || 'As submitted on record'

  const respCitations = (result.respondent.citations || [])
    .map((c) => (typeof c === 'string' ? c : c.case_name || c.source_file))
    .filter(Boolean)
    .join('; ') || 'As submitted on record'

  const formatText = (text) => {
    if (!text) return ''
    return text
      .split('\n\n')
      .map((p) => `<p style="margin-bottom: 12px; line-height: 1.7; text-align: justify;">${p.replace(/\n/g, '<br/>')}</p>`)
      .join('')
  }

  const printWindow = window.open('', '_blank', 'width=900,height=1000')
  if (!printWindow) {
    alert('Please allow popups to download the Certified Court Order.')
    return
  }

  const html = `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <title>Certified Court Order — ${orderNo}</title>
  <style>
    @import url('https://fonts.googleapis.com/css2?family=Cinzel:wght@600;700;800;900&family=Source+Serif+4:ital,wght@0,400;0,600;0,700;1,400&display=swap');
    
    @page {
      size: A4;
      margin: 20mm 18mm 20mm 18mm;
    }
    
    body {
      font-family: 'Source Serif 4', Georgia, serif;
      font-size: 13.5px;
      line-height: 1.65;
      color: #1a1a1a;
      background: #fff;
      margin: 0;
      padding: 24px;
    }
    
    .court-header {
      text-align: center;
      border-bottom: 2px solid #000;
      padding-bottom: 14px;
      margin-bottom: 20px;
    }
    
    .emblem {
      font-size: 32px;
      line-height: 1;
      margin-bottom: 6px;
    }
    
    .court-title {
      font-family: 'Cinzel', serif;
      font-size: 19px;
      font-weight: 800;
      letter-spacing: 0.08em;
      text-transform: uppercase;
      margin: 0 0 4px 0;
    }
    
    .court-sub {
      font-family: 'Cinzel', serif;
      font-size: 12px;
      font-weight: 600;
      letter-spacing: 0.12em;
      text-transform: uppercase;
      color: #333;
    }
    
    .case-details {
      display: flex;
      justify-content: space-between;
      font-size: 12px;
      font-weight: 600;
      margin-bottom: 18px;
      border-bottom: 1px dashed #777;
      padding-bottom: 8px;
    }
    
    .memo-parties {
      margin: 18px 0;
      padding: 12px 18px;
      background: #fbf9f4;
      border-left: 3px solid #8b7355;
      font-size: 13px;
    }
    
    .disposition-box {
      margin: 24px 0;
      padding: 14px 20px;
      border: 2px solid #1a1a1a;
      background: #faf8f5;
      text-align: center;
    }
    
    .disp-title {
      font-family: 'Cinzel', serif;
      font-size: 12px;
      font-weight: 800;
      letter-spacing: 0.15em;
      text-transform: uppercase;
      color: #666;
    }
    
    .disp-val {
      font-family: 'Cinzel', serif;
      font-size: 18px;
      font-weight: 900;
      color: #1a1a1a;
      margin-top: 4px;
    }
    
    .section-title {
      font-family: 'Cinzel', serif;
      font-size: 13.5px;
      font-weight: 800;
      letter-spacing: 0.06em;
      text-transform: uppercase;
      margin: 24px 0 10px 0;
      border-bottom: 1px solid #ccc;
      padding-bottom: 4px;
      color: #222;
    }
    
    .seal-wrap {
      display: flex;
      justify-content: space-between;
      align-items: flex-end;
      margin-top: 50px;
      padding-top: 20px;
      page-break-inside: avoid;
    }
    
    .seal-circle {
      width: 110px;
      height: 110px;
      border: 3px double #8b7355;
      border-radius: 50%;
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      text-align: center;
      font-family: 'Cinzel', serif;
      font-size: 8px;
      font-weight: 700;
      color: #8b7355;
      letter-spacing: 0.05em;
      padding: 6px;
      box-sizing: border-box;
    }
    
    .sig-line {
      text-align: right;
      font-size: 12px;
    }
    
    .watermark {
      position: fixed;
      top: 50%;
      left: 50%;
      transform: translate(-50%, -50%) rotate(-30deg);
      font-family: 'Cinzel', serif;
      font-size: 65px;
      font-weight: 900;
      color: rgba(0, 0, 0, 0.035);
      letter-spacing: 0.15em;
      pointer-events: none;
      z-index: 0;
      white-space: nowrap;
    }
    
    .no-print {
      position: fixed;
      top: 14px;
      right: 14px;
      z-index: 100;
    }
    .print-btn {
      background: #1a1a1a;
      color: #fff;
      border: 0;
      padding: 9px 18px;
      font-family: 'Cinzel', serif;
      font-size: 12px;
      font-weight: 700;
      letter-spacing: 0.08em;
      cursor: pointer;
      border-radius: 4px;
      box-shadow: 0 4px 12px rgba(0,0,0,0.15);
    }
    
    @media print {
      .no-print { display: none; }
      body { padding: 0; }
    }
  </style>
</head>
<body>
  <div class="watermark">CERTIFIED COURT DECREE</div>

  <div class="no-print">
    <button class="print-btn" onclick="window.print()">🖨️ Print / Save as PDF</button>
  </div>

  <div class="court-header">
    <div class="emblem">⚖</div>
    <h1 class="court-title">In the High Court of Judicature</h1>
    <div class="court-sub">Appellate & Original Jurisdiction · Division Bench</div>
  </div>

  <div class="case-details">
    <div><strong>ORDER REFERENCE:</strong> ${orderNo}</div>
    <div><strong>DATE OF PRONOUNCEMENT:</strong> ${dateStr}</div>
  </div>

  <div class="memo-parties">
    <p style="margin: 0 0 6px 0;"><strong>SPECIAL PROPOSITION / DISPUTE BEFORE BENCH:</strong></p>
    <p style="margin: 0; font-style: italic;">"${result.dispute}"</p>
  </div>

  <div class="disposition-box">
    <div class="disp-title">Operative Judicial Disposition</div>
    <div class="disp-val">${result.bench.disposition}</div>
    <div style="font-size: 12px; color: #555; margin-top: 4px;">Prevailing Side: <strong>${result.bench.prevailing_party}</strong></div>
  </div>

  <div class="section-title">I. Submissions on Behalf of Petitioner</div>
  <div style="font-size: 11.5px; color: #555; margin-bottom: 8px;">
    <strong>Senior Counsel for Petitioner</strong> · Engine: ${result.petitioner.model || 'Groq Law Engine'}
    <br/><em>Authorities Cited:</em> ${petCitations}
  </div>
  ${formatText(result.petitioner.argument)}

  <div class="section-title">II. Submissions on Behalf of Respondent</div>
  <div style="font-size: 11.5px; color: #555; margin-bottom: 8px;">
    <strong>Senior Counsel for Respondent</strong> · Engine: ${result.respondent.model || 'Groq Defense Engine'}
    <br/><em>Authorities Cited:</em> ${respCitations}
  </div>
  ${formatText(result.respondent.argument)}

  ${interlocutoryThreads.length > 0 ? `
    <div class="section-title">III. Interlocutory Inquiries of the Bench</div>
    ${interlocutoryThreads.map((th, i) => `
      <div style="margin-bottom: 12px; padding: 10px 14px; background: #faf9f6; border-left: 2px solid #666; font-size: 12.5px;">
        <p style="margin: 0 0 4px 0; font-weight: 700;">Question from Bench [${i + 1}]: "${th.question}"</p>
        <p style="margin: 0; font-style: italic;"><strong>${th.counselTitle}:</strong> ${th.response}</p>
      </div>
    `).join('')}
  ` : ''}

  <div class="section-title">IV. Reasoned Order & Ratio Decidendi of the Bench</div>
  <div style="font-size: 11.5px; color: #555; margin-bottom: 8px;">
    <strong>Delivered by the Presiding Bench</strong> · Engine: ${result.bench.model || 'Gemini Flash Legal Engine'}
  </div>
  ${formatText(result.bench.verdict)}

  <div class="seal-wrap">
    <div class="seal-circle">
      <div style="font-size: 14px; margin-bottom: 2px;">⚖</div>
      <div>HIGH COURT</div>
      <div style="font-size: 6.5px;">SEAL OF RECORD</div>
      <div style="font-size: 7px; margin-top: 2px;">CERTIFIED</div>
    </div>
    
    <div class="sig-line">
      <div style="font-family: 'Cinzel', serif; font-weight: 700; font-size: 13px;">By Order of the Division Bench</div>
      <div style="color: #666; font-size: 11.5px; margin-top: 3px;">Registrar (Judicial) / LexAI Command Centre</div>
      <div style="color: #888; font-size: 10.5px;">Issued electronically under Rule 14-B</div>
    </div>
  </div>
</body>
</html>`

  printWindow.document.write(html)
  printWindow.document.close()
}
