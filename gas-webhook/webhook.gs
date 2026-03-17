/**
 * NICU/PICU Journal Bot - LINE Webhook (Google Apps Script)
 * 
 * This script handles:
 * 1. Feedback postback from LINE (must_read, useful, so_so, skip)
 * 2. On-demand deep analysis requests
 * 
 * Setup:
 * 1. Go to https://script.google.com → New project
 * 2. Paste this entire script
 * 3. Add Script Properties (Settings → Script Properties):
 *    - LINE_CHANNEL_ACCESS_TOKEN: Your LINE Bot channel access token
 *    - ANTHROPIC_API_KEY: Your Claude API key
 *    - GITHUB_TOKEN: Personal access token (for updating feedback.json)
 *    - GITHUB_REPO: lantus123/journal-review-bot
 * 4. Deploy → New deployment → Web app
 *    - Execute as: Me
 *    - Who has access: Anyone
 * 5. Copy the Web app URL → Set as LINE Webhook URL in LINE Developers
 */

// ============================================
// LINE Webhook Handler
// ============================================

function doPost(e) {
  try {
    var body = JSON.parse(e.postData.contents);
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

function doGet(e) {
  return ContentService.createTextOutput("NICU/PICU Journal Bot Webhook Active")
    .setMimeType(ContentService.MimeType.TEXT);
}


// ============================================
// Postback Handler
// ============================================

function handlePostback(event) {
  var data = parsePostbackData(event.postback.data);
  var userId = event.source.userId || "anonymous";
  
  if (data.action === "feedback") {
    handleFeedback(data.pmid, data.rating, userId);
  } else if (data.action === "deep_analysis") {
    handleDeepAnalysisRequest(data.pmid, userId, event.replyToken);
  }
}

function parsePostbackData(dataStr) {
  var params = {};
  var pairs = dataStr.split("&");
  for (var i = 0; i < pairs.length; i++) {
    var kv = pairs[i].split("=");
    if (kv.length === 2) {
      params[kv[0]] = kv[1];
    }
  }
  return params;
}


// ============================================
// Feedback Handler
// ============================================

function handleFeedback(pmid, rating, userId) {
  console.log("Feedback: PMID " + pmid + " = " + rating + " by " + userId.substring(0, 8));
  
  // Save to GitHub repo's feedback.json
  saveFeedbackToGitHub(pmid, rating, userId);
  
  // Quick reply to user
  var token = getProperty("LINE_CHANNEL_ACCESS_TOKEN");
  // No reply needed for feedback - the postback displayText handles it
}


function saveFeedbackToGitHub(pmid, rating, userId) {
  try {
    var repo = getProperty("GITHUB_REPO");
    var githubToken = getProperty("GITHUB_TOKEN");
    var path = "data/feedback.json";
    
    // Get current file
    var fileData = getGitHubFile(repo, path, githubToken);
    var feedback = [];
    
    if (fileData && fileData.content) {
      feedback = JSON.parse(Utilities.newBlob(Utilities.base64Decode(fileData.content.replace(/\n/g, ""))).getDataAsString());
    }
    
    // Add or update feedback
    var now = new Date().toISOString();
    var found = false;
    for (var i = 0; i < feedback.length; i++) {
      if (feedback[i].pmid === pmid && feedback[i].user_id === userId) {
        feedback[i].rating = rating;
        feedback[i].timestamp = now;
        found = true;
        break;
      }
    }
    if (!found) {
      feedback.push({
        pmid: pmid,
        rating: rating,
        source: "line",
        user_id: userId,
        timestamp: now
      });
    }
    
    // Update file on GitHub
    var content = Utilities.base64Encode(JSON.stringify(feedback, null, 2));
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

function handleDeepAnalysisRequest(pmid, userId, replyToken) {
  console.log("On-demand request: PMID " + pmid + " by " + userId.substring(0, 8));
  
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
  saveOnDemandToGitHub(pmid, userId, article, analysis);
  
  console.log("On-demand analysis complete for PMID " + pmid);
}


function fetchPubMedArticle(pmid) {
  try {
    var url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?db=pubmed&id=" + pmid + "&rettype=xml&retmode=xml";
    var resp = UrlFetchApp.fetch(url, { muteHttpExceptions: true });
    var xml = resp.getContentText();
    
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
    
    var data = JSON.parse(resp.getContentText());
    var text = data.content[0].text;
    
    // Strip markdown fences
    text = text.replace(/^```json\s*/, "").replace(/```\s*$/, "").trim();
    
    return JSON.parse(text);
    
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

function saveOnDemandToGitHub(pmid, userId, article, analysis) {
  try {
    var repo = getProperty("GITHUB_REPO");
    var githubToken = getProperty("GITHUB_TOKEN");
    var path = "data/on_demand_queue.json";
    
    var fileData = getGitHubFile(repo, path, githubToken);
    var queue = [];
    
    if (fileData && fileData.content) {
      queue = JSON.parse(Utilities.newBlob(Utilities.base64Decode(fileData.content.replace(/\n/g, ""))).getDataAsString());
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
    
    var content = Utilities.base64Encode(JSON.stringify(queue, null, 2));
    updateGitHubFile(repo, path, content, fileData ? fileData.sha : null,
                     "On-demand analysis: PMID " + pmid, githubToken);
    
  } catch (err) {
    console.error("Error saving on-demand to GitHub:", err);
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
      return JSON.parse(resp.getContentText());
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
