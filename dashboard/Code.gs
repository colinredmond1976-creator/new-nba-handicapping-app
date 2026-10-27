const PAYLOAD_URL = 'https://raw.githubusercontent.com/colinredmond1976-creator/new-nba-handicapping-app/main/data/dashboard_payload.json';
const CACHE_KEY = 'dashboard_payload';

function doGet(e) {
  return HtmlService.createHtmlOutputFromFile('Index').setTitle('NBA Handicapping Dashboard');
}

function getDashboardData() {
  const cache = CacheService.getScriptCache();
  try {
    const response = UrlFetchApp.fetch(PAYLOAD_URL, {muteHttpExceptions: true});
    if (response.getResponseCode() !== 200) throw new Error('Payload request failed: HTTP ' + response.getResponseCode());
    const raw = response.getContentText();
    const payload = JSON.parse(raw);
    if (!payload.heartbeat || !payload.summary || !Array.isArray(payload.todays_cards) || !Array.isArray(payload.history)) {
      throw new Error('Invalid dashboard payload');
    }
    try { cache.put(CACHE_KEY, raw, 21600); } catch (cacheError) { console.warn('Payload cache unavailable: ' + cacheError.message); }
    payload._dashboard_source = 'live';
    return payload;
  } catch (error) {
    const cached = cache.get(CACHE_KEY);
    if (!cached) throw new Error('Dashboard data unavailable: ' + error.message);
    const payload = JSON.parse(cached);
    payload._dashboard_source = 'cache';
    return payload;
  }
}
