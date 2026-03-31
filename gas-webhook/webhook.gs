/**
 * NICU/PICU Journal Bot - LINE + Web/Email Webhook (Google Apps Script)
 *
 * This script handles:
 * 1. LINE postback: feedback + on-demand deep analysis (POST)
 * 2. Web/Email feedback via GET (JSONP for web, thank-you page for email)
 *
 * Setup:
 * 1. Go to https://script.google.com → New project
 * 2. Paste this entire script
 * 3. Add Script Properties (Settings → Script Properties):
 *    - LINE_CHANNEL_ACCESS_TOKEN: Your LINE Bot channel access token
 *    - ANTHROPIC_API_KEY: Your Claude API key
 *    - GITHUB_TOKEN: Personal access token (for updating feedback.json)
 *    - GITHUB_REPO: lantus123/journal-review-bot
 *    - FEEDBACK_SECRET: Shared secret for web/email feedback verification
 * 4. Deploy → New deployment → Web app
 *    - Execute as: Me
 *    - Who has access: Anyone
 * 5. Copy the Web app URL → Set as LINE Webhook URL in LINE Developers
 */

// ============================================
// LINE Webhook Handler (POST)
// ============================================

function doPost(e) {
  try {
    // Handle form-encoded POST (from hidden iframe upload)
    var params = e.parameter || {};
    if (params.action === "upload_pdf") {
      return handlePdfUpload(params);
    }

    var body = JSON.parse(e.postData.contents);

    // PDF upload from JSON POST (legacy)
    if (body.action === "upload_pdf") {
      return handlePdfUpload(body);
    }

    // LINE webhook
    var events = body.events || [];

    for (var i = 0; i < events.length; i++) {
      var event = events[i];

      if (event.type === "postback") {
        handlePostback(event);
      }
    }

    return ContentService.createTextOutput(JSON.stringify({ status: "ok" }))
      .setMimeType(ContentService.MimeType.JSON);

  } catch (err) {
    console.error("Webhook error:", err);
    return ContentService.createTextOutput(JSON.stringify({ status: "error", message: err.message }))
      .setMimeType(ContentService.MimeType.JSON);
  }
}


// ============================================
// Web/Email Feedback Handler (GET)
// ============================================

function doGet(e) {
  var params = e.parameter || {};
  var action = params.action || "";

  // Health check
  if (action !== "feedback" && action !== "check_pdf") {
    return ContentService.createTextOutput("NICU/PICU Journal Bot Webhook Active")
      .setMimeType(ContentService.MimeType.TEXT);
  }

  // Check PDF analysis status (JSONP)
  if (action === "check_pdf") {
    var pmid = params.pmid || "";
    var secret = params.secret || "";
    var callback = params.callback || "";
    var dept = validateDept(params.dept);

    var expectedSecret = getProperty("FEEDBACK_SECRET");
    if (expectedSecret && secret !== expectedSecret) {
      var errResp = callback + '({"status":"error","message":"Unauthorized"})';
      return ContentService.createTextOutput(errResp).setMimeType(ContentService.MimeType.JAVASCRIPT);
    }

    if (!pmid) {
      var errResp = callback + '({"status":"error","message":"Missing pmid"})';
      return ContentService.createTextOutput(errResp).setMimeType(ContentService.MimeType.JAVASCRIPT);
    }

    var repo = getProperty("GITHUB_REPO");
    var githubToken = getProperty("GITHUB_TOKEN");
    var existing = getGitHubFile(repo, "data/" + dept + "/pdf_analyses/" + pmid + ".json", githubToken);

    if (existing && existing.content) {
      var analysis = JSON.parse(
        Utilities.newBlob(Utilities.base64Decode(existing.content.replace(/\n/g, ""))).getDataAsString("UTF-8")
      );
      var okResp = callback + '(' + JSON.stringify({ status: "ok", analysis: analysis, cached: true }) + ')';
      return ContentService.createTextOutput(okResp).setMimeType(ContentService.MimeType.JAVASCRIPT);
    }

    var pendingResp = callback + '({"status":"pending"})';
    return ContentService.createTextOutput(pendingResp).setMimeType(ContentService.MimeType.JAVASCRIPT);
  }

  // Validate required params
  var pmid = params.pmid || "";
  var rating = params.rating || "";
  var source = params.source || "unknown";
  var uid = params.uid || "anonymous";
  var secret = params.secret || "";
  var callback = params.callback || "";
  var dept = validateDept(params.dept);

  if (!pmid || !rating) {
    var errMsg = "Missing pmid or rating";
    if (callback) {
      return ContentService.createTextOutput(callback + "({\"status\":\"error\",\"message\":\"" + errMsg + "\"})")
        .setMimeType(ContentService.MimeType.JAVASCRIPT);
    }
    return HtmlService.createHtmlOutput("<html><body><h2>Error</h2><p>" + errMsg + "</p></body></html>");
  }

  // Validate secret
  var expectedSecret = getProperty("FEEDBACK_SECRET");
  if (expectedSecret && secret !== expectedSecret) {
    var errMsg = "Invalid secret";
    if (callback) {
      return ContentService.createTextOutput(callback + "({\"status\":\"error\",\"message\":\"" + errMsg + "\"})")
        .setMimeType(ContentService.MimeType.JAVASCRIPT);
    }
    return HtmlService.createHtmlOutput("<html><body><h2>Error</h2><p>Unauthorized</p></body></html>");
  }

  // Save feedback
  saveFeedbackToGitHub(pmid, rating, uid, source, dept);

  // Return response based on source
  if (callback) {
    // JSONP response for web
    return ContentService.createTextOutput(
      callback + "({\"status\":\"ok\",\"pmid\":\"" + pmid + "\",\"rating\":\"" + rating + "\"})"
    ).setMimeType(ContentService.MimeType.JAVASCRIPT);
  }

  // HTML thank-you page for email clicks
  var ratingLabels = {
    "must_read": "🔥 Must Read",
    "useful": "👍 Useful",
    "so_so": "➖ So-so",
    "skip": "👎 Skip"
  };
  var ratingDisplay = ratingLabels[rating] || rating;

  var html = '<!DOCTYPE html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">' +
    '<style>body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;display:flex;justify-content:center;align-items:center;min-height:100vh;margin:0;background:#f7f7f3}' +
    '.card{background:#fff;border-radius:16px;padding:40px;text-align:center;box-shadow:0 2px 12px rgba(0,0,0,0.08);max-width:400px}' +
    'h2{color:#1B6B93;margin:0 0 12px}p{color:#666;margin:0 0 8px;font-size:14px}.rating{font-size:24px;margin:16px 0}' +
    '.pmid{font-size:12px;color:#999}</style></head><body><div class="card">' +
    '<h2>感謝回饋！</h2>' +
    '<div class="rating">' + ratingDisplay + '</div>' +
    '<p>您的回饋將幫助我們優化文章評分</p>' +
    '<p class="pmid">PMID: ' + pmid + '</p>' +
    '</div></body></html>';

  return HtmlService.createHtmlOutput(html);
}


// ============================================
// Department Validation
// ============================================

var VALID_DEPTS = ["newborn", "cardiology"];

function validateDept(dept) {
  if (dept && VALID_DEPTS.indexOf(dept) !== -1) return dept;
  return "newborn";
}


/**
 * Robustly parse JSON from Claude API response.
 * Handles markdown fences, trailing commas, and extracts JSON object if surrounded by text.
 */
function parseJsonFromLLM(resp) {
  var data = JSON.parse(resp.getContentText("UTF-8"));

  // Check for API error
  if (data.type === "error" || !data.content || !data.content[0]) {
    console.error("API error:", JSON.stringify(data));
    return null;
  }

  var text = data.content[0].text;

  // Strip markdown fences (```json ... ``` or ``` ... ```)
  text = text.replace(/^```(?:json)?\s*\n?/, "").replace(/\n?```\s*$/, "").trim();

  // Try direct parse first
  try {
    return JSON.parse(text);
  } catch (e) {
    // Fallback: extract the first { ... } block
    var match = text.match(/\{[\s\S]*\}/);
    if (match) {
      try {
        return JSON.parse(match[0]);
      } catch (e2) {
        // Try fixing trailing commas: ,} → } and ,] → ]
        var fixed = match[0].replace(/,\s*([}\]])/g, "$1");
        return JSON.parse(fixed);
      }
    }
    throw new Error("Could not parse JSON from LLM response: " + text.substring(0, 200));
  }
}


// ============================================
// Postback Handler (LINE)
// ============================================

function handlePostback(event) {
  var data = parsePostbackData(event.postback.data);
  var userId = event.source.userId || "anonymous";
  var dept = validateDept(data.dept);

  if (data.action === "feedback") {
    handleFeedback(data.pmid, data.rating, userId, dept);
  } else if (data.action === "deep_analysis") {
    handleDeepAnalysisRequest(data.pmid, userId, event.replyToken, dept);
  }
}

function parsePostbackData(dataStr) {
  var params = {};
  var pairs = dataStr.split("&");
  for (var i = 0; i < pairs.length; i++) {
    var kv = pairs[i].split("=");
    if (kv.length === 2) {
      params[kv[0]] = decodeURIComponent(kv[1]);
    }
  }
  return params;
}


// ============================================
// Feedback Handler
// ============================================

function handleFeedback(pmid, rating, userId, dept) {
  console.log("Feedback: PMID " + pmid + " = " + rating + " by " + userId.substring(0, 8) + " dept=" + dept);
  saveFeedbackToGitHub(pmid, rating, "line_" + userId, "line", dept);
}


function saveFeedbackToGitHub(pmid, rating, userId, source, dept) {
  dept = dept || "newborn";
  try {
    var repo = getProperty("GITHUB_REPO");
    var githubToken = getProperty("GITHUB_TOKEN");
    var path = "data/" + dept + "/feedback.json";

    // Get current file
    var fileData = getGitHubFile(repo, path, githubToken);
    var feedback = [];

    if (fileData && fileData.content) {
      feedback = JSON.parse(
        Utilities.newBlob(
          Utilities.base64Decode(fileData.content.replace(/\n/g, ""))
        ).getDataAsString("UTF-8")
      );
    }

    // Add or update feedback
    var now = new Date().toISOString();
    var found = false;
    for (var i = 0; i < feedback.length; i++) {
      if (feedback[i].pmid === pmid && feedback[i].user_id === userId) {
        feedback[i].rating = rating;
        feedback[i].timestamp = now;
        feedback[i].source = source;
        found = true;
        break;
      }
    }
    if (!found) {
      feedback.push({
        pmid: pmid,
        rating: rating,
        source: source,
        user_id: userId,
        timestamp: now
      });
    }

    // Update file on GitHub
    var contentBytes = Utilities.newBlob(JSON.stringify(feedback, null, 2), "text/plain", "feedback.json").getBytes();
    var content = Utilities.base64Encode(contentBytes);
    updateGitHubFile(repo, path, content, fileData ? fileData.sha : null,
                     "Feedback: PMID " + pmid + " = " + rating, githubToken);

    console.log("Feedback saved to GitHub");
  } catch (err) {
    console.error("Error saving feedback to GitHub:", err);
  }
}


// ============================================
// On-Demand Deep Analysis
// ============================================

function handleDeepAnalysisRequest(pmid, userId, replyToken, dept) {
  dept = dept || "newborn";
  console.log("On-demand request: PMID " + pmid + " by " + userId.substring(0, 8) + " dept=" + dept);

  // 1. Reply immediately: "Analyzing..."
  replyMessage(replyToken, "正在使用 Sonnet 進行深度分析，大約需要 60 秒...\nPMID: " + pmid);

  // 2. Fetch article info from PubMed
  var article = fetchPubMedArticle(pmid);
  if (!article) {
    pushMessage(userId, "抱歉，無法從 PubMed 取得 PMID " + pmid + " 的資料。");
    return;
  }

  // 3. Call Claude Sonnet for deep analysis
  var analysis = callSonnetAnalysis(article);
  if (!analysis) {
    pushMessage(userId, "抱歉，AI 分析過程中發生錯誤，請稍後再試。");
    return;
  }

  // 4. Build result article object
  article.deep_analysis = analysis;
  article.total_score = article.total_score || 3;

  // 5. Push result to the requesting user
  var resultText = formatDeepAnalysisText(article, analysis);
  pushMessage(userId, resultText);

  // 6. Save to on-demand queue for tomorrow's digest
  saveOnDemandToGitHub(pmid, userId, article, analysis, dept);

  console.log("On-demand analysis complete for PMID " + pmid);
}


function fetchPubMedArticle(pmid) {
  try {
    var url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?db=pubmed&id=" + pmid + "&rettype=xml&retmode=xml";
    var resp = UrlFetchApp.fetch(url, { muteHttpExceptions: true });
    var xml = resp.getContentText("UTF-8");

    // Simple XML parsing
    var title = extractXml(xml, "ArticleTitle") || "Unknown title";
    var abstractParts = [];
    var abstractTexts = xml.match(/<AbstractText[^>]*>([\s\S]*?)<\/AbstractText>/g) || [];
    for (var i = 0; i < abstractTexts.length; i++) {
      var text = abstractTexts[i].replace(/<[^>]+>/g, "");
      abstractParts.push(text);
    }
    var abstract = abstractParts.join("\n") || "No abstract available";

    // Authors
    var authors = [];
    var lastNames = xml.match(/<LastName>(.*?)<\/LastName>/g) || [];
    var initials = xml.match(/<Initials>(.*?)<\/Initials>/g) || [];
    for (var i = 0; i < Math.min(lastNames.length, 3); i++) {
      var ln = lastNames[i].replace(/<[^>]+>/g, "");
      var init = initials[i] ? initials[i].replace(/<[^>]+>/g, "") : "";
      authors.push(ln + " " + init);
    }
    if (lastNames.length > 3) authors.push("et al.");

    // Journal
    var journal = extractXml(xml, "Title") || "";

    // DOI
    var doi = "";
    var doiMatch = xml.match(/<ELocationID EIdType="doi"[^>]*>(.*?)<\/ELocationID>/);
    if (doiMatch) doi = doiMatch[1];

    return {
      pmid: pmid,
      title: title,
      abstract: abstract,
      authors: authors.join(", "),
      journal: journal,
      doi: doi,
      source_journal: journal
    };
  } catch (err) {
    console.error("PubMed fetch error:", err);
    return null;
  }
}


function callSonnetAnalysis(article) {
  try {
    var apiKey = getProperty("ANTHROPIC_API_KEY");

    var prompt = "你是一位台灣馬偕紀念醫院的新生兒/兒童重症專科資深主治醫師。\n" +
      "請針對以下文章做深度分析，用繁體中文回覆。\n" +
      "臨床常用英文縮寫和藥物名稱保留英文，統計數據保留原始格式。\n\n" +
      "回覆純 JSON：\n" +
      '{"thirty_second_summary":"<30秒重點>",' +
      '"hidden_findings":[{"finding":"<發現>","implication":"<意義>"}],' +
      '"methodology_audit":{"strengths":["<優點>"],"weaknesses":["<缺陷>"]},' +
      '"evidence_positioning":{"guideline_status":"<指引現況>","evidence_gap_filled":"<填補的gap>"},' +
      '"protocol_impact":{"current_practice":"<一般做法>","proposed_change":"<建議調整>","missing_evidence":"<缺少的證據>"}}\n\n' +
      "Article:\n" +
      "Title: " + article.title + "\n" +
      "Journal: " + article.journal + "\n" +
      "Authors: " + article.authors + "\n" +
      "PMID: " + article.pmid + "\n\n" +
      "Abstract:\n" + article.abstract;

    var payload = {
      model: "claude-sonnet-4-20250514",
      max_tokens: 4096,
      temperature: 0.2,
      messages: [{ role: "user", content: prompt }]
    };

    var resp = UrlFetchApp.fetch("https://api.anthropic.com/v1/messages", {
      method: "post",
      contentType: "application/json",
      headers: {
        "x-api-key": apiKey,
        "anthropic-version": "2023-06-01"
      },
      payload: JSON.stringify(payload),
      muteHttpExceptions: true
    });

    return parseJsonFromLLM(resp);

  } catch (err) {
    console.error("Sonnet analysis error:", err);
    return null;
  }
}


function formatDeepAnalysisText(article, analysis) {
  var lines = [];
  lines.push("📋 Deep Analysis Complete");
  lines.push("━━━━━━━━━━━━━━━━━━━━");
  lines.push(article.title);
  lines.push(article.authors + " · " + article.journal);
  lines.push("");

  if (analysis.thirty_second_summary) {
    lines.push("🎯 30 秒重點");
    lines.push(analysis.thirty_second_summary);
    lines.push("");
  }

  if (analysis.hidden_findings && analysis.hidden_findings.length > 0) {
    lines.push("🔍 Abstract 沒告訴你的事");
    for (var i = 0; i < analysis.hidden_findings.length; i++) {
      lines.push("• " + analysis.hidden_findings[i].finding);
    }
    lines.push("");
  }

  var meth = analysis.methodology_audit || {};
  if (meth.strengths && meth.strengths.length > 0) {
    lines.push("✅ Strong: " + meth.strengths[0]);
  }
  if (meth.weaknesses && meth.weaknesses.length > 0) {
    lines.push("⚠️ Weak: " + meth.weaknesses[0]);
  }
  lines.push("");

  var impact = analysis.protocol_impact || {};
  if (impact.proposed_change) {
    lines.push("🏥 對我們科的影響");
    lines.push(impact.proposed_change);
  }

  lines.push("");
  lines.push("PubMed: https://pubmed.ncbi.nlm.nih.gov/" + article.pmid + "/");

  return lines.join("\n");
}


// ============================================
// On-Demand Queue (save to GitHub for next day digest)
// ============================================

function saveOnDemandToGitHub(pmid, userId, article, analysis, dept) {
  dept = dept || "newborn";
  try {
    var repo = getProperty("GITHUB_REPO");
    var githubToken = getProperty("GITHUB_TOKEN");
    var path = "data/" + dept + "/on_demand_queue.json";

    var fileData = getGitHubFile(repo, path, githubToken);
    var queue = [];

    if (fileData && fileData.content) {
      queue = JSON.parse(
        Utilities.newBlob(
          Utilities.base64Decode(fileData.content.replace(/\n/g, ""))
        ).getDataAsString("UTF-8")
      );
    }

    // Add article with analysis
    queue.push({
      pmid: pmid,
      user_id: userId,
      timestamp: new Date().toISOString(),
      title: article.title,
      authors: article.authors,
      source_journal: article.journal,
      total_score: article.total_score || 3,
      deep_analysis: analysis,
      summary: {
        purpose: "",
        design: "",
        findings: analysis.thirty_second_summary || "",
        significance: (analysis.protocol_impact || {}).proposed_change || ""
      }
    });

    var contentBytes = Utilities.newBlob(JSON.stringify(queue, null, 2), "text/plain", "queue.json").getBytes();
    var content = Utilities.base64Encode(contentBytes);
    updateGitHubFile(repo, path, content, fileData ? fileData.sha : null,
                     "On-demand analysis: PMID " + pmid, githubToken);

  } catch (err) {
    console.error("Error saving on-demand to GitHub:", err);
  }
}


// ============================================
// PDF Upload + Instant Full-Text Analysis
// ============================================

function handlePdfUpload(body) {
  var pmid = body.pmid || "";
  var title = body.title || "";
  var pdfBase64 = body.pdf_base64 || "";
  var secret = body.secret || "";
  var dept = validateDept(body.dept);

  // Validate
  var expectedSecret = getProperty("FEEDBACK_SECRET");
  if (expectedSecret && secret !== expectedSecret) {
    return ContentService.createTextOutput(JSON.stringify({ status: "error", message: "Unauthorized" }))
      .setMimeType(ContentService.MimeType.JSON);
  }

  if (!pmid || !pdfBase64) {
    return ContentService.createTextOutput(JSON.stringify({ status: "error", message: "Missing pmid or pdf_base64" }))
      .setMimeType(ContentService.MimeType.JSON);
  }

  if (!/^\d+$/.test(pmid)) {
    return ContentService.createTextOutput(JSON.stringify({ status: "error", message: "Invalid PMID" }))
      .setMimeType(ContentService.MimeType.JSON);
  }

  try {
    var repo = getProperty("GITHUB_REPO");
    var githubToken = getProperty("GITHUB_TOKEN");

    // 1. Check if analysis already exists
    var existingAnalysis = getGitHubFile(repo, "data/" + dept + "/pdf_analyses/" + pmid + ".json", githubToken);
    if (existingAnalysis && existingAnalysis.content) {
      var existing = JSON.parse(
        Utilities.newBlob(
          Utilities.base64Decode(existingAnalysis.content.replace(/\n/g, ""))
        ).getDataAsString("UTF-8")
      );
      return ContentService.createTextOutput(JSON.stringify({ status: "ok", analysis: existing, cached: true }))
        .setMimeType(ContentService.MimeType.JSON);
    }

    // 2. Commit PDF to GitHub
    var pdfPath = "data/" + dept + "/pdfs/" + pmid + ".pdf";
    var existingPdf = getGitHubFile(repo, pdfPath, githubToken);
    updateGitHubFile(repo, pdfPath, pdfBase64, existingPdf ? existingPdf.sha : null,
                     "Upload PDF: PMID " + pmid, githubToken);

    // 3. Extract text from PDF via Google Drive
    var extractResult = extractPdfText(pdfBase64);
    if (extractResult.error) {
      return ContentService.createTextOutput(JSON.stringify({ status: "error", message: "PDF text extraction failed: " + extractResult.error }))
        .setMimeType(ContentService.MimeType.JSON);
    }
    var fulltext = extractResult.text;

    // 4. Fetch article metadata from PubMed
    var article = fetchPubMedArticle(pmid);
    if (!article) {
      article = { pmid: pmid, title: title, abstract: "", authors: "", journal: "", doi: "" };
    }

    // 5. Call Sonnet with full text
    var analysis = callSonnetWithFulltext(article, fulltext);
    if (!analysis) {
      return ContentService.createTextOutput(JSON.stringify({ status: "error", message: "AI analysis failed" }))
        .setMimeType(ContentService.MimeType.JSON);
    }

    // 6. Save analysis result to GitHub
    var result = {
      pmid: pmid,
      title: article.title,
      authors: article.authors,
      source_journal: article.journal,
      deep_analysis: analysis,
      fulltext_source: "manual",
      analyzed_at: new Date().toISOString()
    };

    var resultJson = JSON.stringify(result, null, 2);
    var resultBase64 = Utilities.base64Encode(
      Utilities.newBlob(resultJson, "text/plain").getBytes()
    );
    updateGitHubFile(repo, "data/" + dept + "/pdf_analyses/" + pmid + ".json", resultBase64, null,
                     "PDF analysis: PMID " + pmid, githubToken);

    return ContentService.createTextOutput(JSON.stringify({ status: "ok", analysis: result, cached: false }))
      .setMimeType(ContentService.MimeType.JSON);

  } catch (err) {
    console.error("PDF upload error:", err);
    return ContentService.createTextOutput(JSON.stringify({ status: "error", message: err.message }))
      .setMimeType(ContentService.MimeType.JSON);
  }
}


function extractPdfText(pdfBase64) {
  var fileId = null;
  try {
    // Upload PDF to Google Drive, convert to Google Docs (Drive API v3)
    var pdfBlob = Utilities.newBlob(Utilities.base64Decode(pdfBase64), "application/pdf", "upload.pdf");
    var resource = {
      name: "temp_pdf_" + Date.now(),
      mimeType: "application/vnd.google-apps.document"  // convert to Google Doc
    };
    var file = Drive.Files.create(resource, pdfBlob, { ocrLanguage: "en" });
    fileId = file.id;

    // Read text from converted Google Doc
    var doc = DocumentApp.openById(fileId);
    var text = doc.getBody().getText();

    // Clean up: move to trash then delete permanently
    Drive.Files.update({ trashed: true }, fileId);
    fileId = null;

    if (!text || text.trim().length < 50) {
      return { error: "Extracted text too short (" + (text ? text.trim().length : 0) + " chars). PDF may be image-only." };
    }

    // Truncate to 8000 chars
    if (text.length > 8000) {
      text = text.substring(0, 8000) + "\n\n[... truncated]";
    }

    return { text: text };
  } catch (err) {
    console.error("PDF text extraction error:", err);
    if (fileId) {
      try { Drive.Files.update({ trashed: true }, fileId); } catch (e) {}
    }
    return { error: err.message };
  }
}


function callSonnetWithFulltext(article, fulltext) {
  try {
    var apiKey = getProperty("ANTHROPIC_API_KEY");

    var prompt = "你是一位台灣馬偕紀念醫院的新生兒/兒童重症專科資深主治醫師。\n" +
      "請針對以下文章做深度分析，用繁體中文回覆。\n" +
      "臨床常用英文縮寫和藥物名稱保留英文，統計數據保留原始格式。\n" +
      "這是完整全文，請特別注意 abstract 沒有提到的次要結果、亞群分析、方法學細節。\n\n" +
      "回覆純 JSON：\n" +
      '{"thirty_second_summary":"<30秒重點>",' +
      '"hidden_findings":[{"finding":"<發現>","source":"<出處章節>","implication":"<意義>"}],' +
      '"methodology_audit":{"strengths":["<優點>"],"notes":["<注意>"],"weaknesses":["<缺陷>"]},' +
      '"evidence_positioning":{"related_studies":[{"citation":"<引用>","comparison":"<比較>"}],"guideline_status":"<指引現況>","evidence_gap_filled":"<填補的gap>","ongoing_trials":"<進行中試驗>"},' +
      '"protocol_impact":{"current_practice":"<一般做法>","proposed_change":"<建議調整>","prerequisites":["<導入準備>"],"missing_evidence":"<缺少的證據>"}}\n\n' +
      "Article:\n" +
      "Title: " + article.title + "\n" +
      "Journal: " + article.journal + "\n" +
      "Authors: " + article.authors + "\n" +
      "PMID: " + article.pmid + "\n\n" +
      "Full text:\n" + fulltext;

    var payload = {
      model: "claude-sonnet-4-20250514",
      max_tokens: 6000,
      temperature: 0.2,
      messages: [{ role: "user", content: prompt }]
    };

    var resp = UrlFetchApp.fetch("https://api.anthropic.com/v1/messages", {
      method: "post",
      contentType: "application/json",
      headers: {
        "x-api-key": apiKey,
        "anthropic-version": "2023-06-01"
      },
      payload: JSON.stringify(payload),
      muteHttpExceptions: true
    });

    return parseJsonFromLLM(resp);

  } catch (err) {
    console.error("Sonnet fulltext analysis error:", err);
    return null;
  }
}


// ============================================
// GitHub API Helpers
// ============================================

function getGitHubFile(repo, path, token) {
  try {
    var url = "https://api.github.com/repos/" + repo + "/contents/" + path;
    var resp = UrlFetchApp.fetch(url, {
      headers: { "Authorization": "token " + token },
      muteHttpExceptions: true
    });
    if (resp.getResponseCode() === 200) {
      return JSON.parse(resp.getContentText("UTF-8"));
    }
    return null;
  } catch (err) {
    return null;
  }
}

function updateGitHubFile(repo, path, contentBase64, sha, message, token) {
  var url = "https://api.github.com/repos/" + repo + "/contents/" + path;
  var payload = {
    message: message,
    content: contentBase64,
  };
  if (sha) payload.sha = sha;

  UrlFetchApp.fetch(url, {
    method: "put",
    contentType: "application/json",
    headers: { "Authorization": "token " + token },
    payload: JSON.stringify(payload),
    muteHttpExceptions: true
  });
}


// ============================================
// LINE API Helpers
// ============================================

function replyMessage(replyToken, text) {
  var token = getProperty("LINE_CHANNEL_ACCESS_TOKEN");
  UrlFetchApp.fetch("https://api.line.me/v2/bot/message/reply", {
    method: "post",
    contentType: "application/json",
    headers: { "Authorization": "Bearer " + token },
    payload: JSON.stringify({
      replyToken: replyToken,
      messages: [{ type: "text", text: text }]
    }),
    muteHttpExceptions: true
  });
}

function pushMessage(userId, text) {
  var token = getProperty("LINE_CHANNEL_ACCESS_TOKEN");
  UrlFetchApp.fetch("https://api.line.me/v2/bot/message/push", {
    method: "post",
    contentType: "application/json",
    headers: { "Authorization": "Bearer " + token },
    payload: JSON.stringify({
      to: userId,
      messages: [{ type: "text", text: text }]
    }),
    muteHttpExceptions: true
  });
}


// ============================================
// Utilities
// ============================================

function getProperty(key) {
  return PropertiesService.getScriptProperties().getProperty(key) || "";
}

function extractXml(xml, tag) {
  var regex = new RegExp("<" + tag + "[^>]*>(.*?)</" + tag + ">", "s");
  var match = xml.match(regex);
  return match ? match[1].replace(/<[^>]+>/g, "").trim() : "";
}
