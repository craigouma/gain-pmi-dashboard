var SERVER = 'realist.surveycto.com';
var FORM_IDS = {
  distribution: 'test_form_one_data_specialist_pmi',
  crop_health: 'test_form_two_data_specialist_pmi',
};
var RETRYABLE_CODES = [429, 500, 502, 503, 504];
var EAT_OFFSET_HOURS = 3;
var NEXT_FORM_PROPERTY = 'NEXT_FORM_TO_REFRESH';
var DATE_COLUMNS = ['submission_date'];

var CHANNEL_COLS = {
  distribution_channel_ngo: 'channel_ngo',
  distribution_channel_direct: 'channel_direct',
  distribution_channel_govt: 'channel_govt',
  distribution_channel_coop: 'channel_coop',
  distribution_channel_agrovet: 'channel_agrovet',
};
var SYMPTOM_COLS = {
  symptoms_observed_yellow: 'symptom_yellow',
  symptoms_observed_stunted: 'symptom_stunted',
  symptoms_observed_wilting: 'symptom_wilting',
  symptoms_observed_none: 'symptom_none',
  symptoms_observed_discoloration: 'symptom_discoloration',
  symptoms_observed_spots: 'symptom_spots',
};

var DISTRIBUTION_COLUMNS = ['unique_farmer_id', 'country', 'region', 'submission_date', 'seed_variety',
  'variety_other', 'is_delivered', 'quantity_kg', 'distribution_challenges'].concat(objectValues(CHANNEL_COLS));

var CROP_HEALTH_COLUMNS = ['unique_farmer_id', 'country', 'region', 'submission_date', 'growth_stage',
  'plant_height_cm', 'height_z_within_stage', 'has_pest_disease', 'additional_observations']
  .concat(objectValues(SYMPTOM_COLS));

var FARMER_MASTER_COLUMNS = ['unique_farmer_id', 'link_status', 'country', 'region', 'country_mismatch',
  'region_mismatch', 'geo_mismatch', 'distribution_submission_date', 'seed_variety', 'is_delivered', 'quantity_kg']
  .concat(objectValues(CHANNEL_COLS))
  .concat(['n_crop_health_visits', 'first_crop_health_date', 'last_crop_health_date', 'latest_growth_stage',
    'latest_plant_height_cm', 'latest_height_z_within_stage', 'has_pest_disease', 'days_between_submissions']);

// SurveyCTO rate limits a full pull ("date=0") to one request per SERVER per 300 seconds, not per
// form. Fetching both forms in the same run always collides with that limit, so each run refreshes
// only one form and reads the other form's most recent cleaned data back from its own sheet tab.
function refreshDashboardData() {
  var props = PropertiesService.getScriptProperties();
  var formKey = props.getProperty(NEXT_FORM_PROPERTY) || 'distribution';
  var otherKey = formKey === 'distribution' ? 'crop_health' : 'distribution';

  var raw;
  try {
    raw = fetchForm(formKey);
  } catch (err) {
    Logger.log('Refresh aborted, fetch failed for ' + formKey + ': ' + err.message);
    return;
  }

  var cleaned, otherCleaned, distribution, cropHealth, farmerMaster;
  try {
    cleaned = formKey === 'distribution' ? cleanDistribution(raw) : cleanCropHealth(raw);
    otherCleaned = readSheetAsObjects(otherKey, columnsFor(otherKey));
    distribution = formKey === 'distribution' ? cleaned : otherCleaned;
    cropHealth = formKey === 'crop_health' ? cleaned : otherCleaned;
    farmerMaster = buildFarmerMaster(distribution, cropHealth);
  } catch (err) {
    Logger.log('Refresh aborted, transform failed for ' + formKey + ': ' + err.message);
    return;
  }

  writeSheet(formKey, cleaned, columnsFor(formKey));
  writeSheet('farmer_master', farmerMaster, FARMER_MASTER_COLUMNS);
  writeMeta(formKey, cleaned.length, raw.length - cleaned.length, farmerMaster.length);
  props.setProperty(NEXT_FORM_PROPERTY, otherKey);
}

function columnsFor(formKey) {
  return formKey === 'distribution' ? DISTRIBUTION_COLUMNS : CROP_HEALTH_COLUMNS;
}

function fetchForm(formKey) {
  var props = PropertiesService.getScriptProperties();
  var user = props.getProperty('SCTO_USER');
  var pass = props.getProperty('SCTO_PASS');
  if (!user || !pass) {
    throw new Error('SCTO_USER and SCTO_PASS must be set in Script Properties');
  }

  var url = 'https://' + SERVER + '/api/v2/forms/data/wide/json/' + FORM_IDS[formKey] + '?date=0';
  var options = {
    method: 'get',
    headers: { Authorization: 'Basic ' + Utilities.base64Encode(user + ':' + pass) },
    muteHttpExceptions: true,
  };

  var lastError = null;
  for (var attempt = 0; attempt < 3; attempt++) {
    var response = UrlFetchApp.fetch(url, options);
    var code = response.getResponseCode();

    if (code === 200) {
      try {
        return JSON.parse(response.getContentText());
      } catch (parseErr) {
        var contentType = response.getHeaders()['Content-Type'] || 'unknown';
        throw new Error(formKey + ': response was not JSON (Content-Type ' + contentType + '), likely an ' +
          'HTML login or error page. Check Script Properties SCTO_USER and SCTO_PASS.');
      }
    }

    lastError = new Error(formKey + ': HTTP ' + code + ', ' + extractErrorDetail(response));
    if (RETRYABLE_CODES.indexOf(code) === -1) {
      throw lastError;
    }
    Utilities.sleep(2000 * (attempt + 1));
  }
  throw lastError;
}

function extractErrorDetail(response) {
  try {
    var body = JSON.parse(response.getContentText());
    return (body.error && body.error.message) || response.getContentText().slice(0, 200);
  } catch (parseErr) {
    return response.getContentText().slice(0, 200);
  }
}

// SurveyCTO's exported SubmissionDate carries no time zone marker. It is assumed to already be East
// Africa Time, so the wall clock value is kept and only offset to UTC for storage, never shifted zones.
function parseSctoDate(raw) {
  var match = /^([A-Za-z]{3}) (\d{1,2}), (\d{4}) (\d{1,2}):(\d{2}):(\d{2}) (AM|PM)$/.exec(raw);
  if (!match) {
    throw new Error('SubmissionDate: cannot parse "' + raw + '"');
  }
  var months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  var monthIndex = months.indexOf(match[1]);
  if (monthIndex === -1) {
    throw new Error('SubmissionDate: unknown month "' + match[1] + '"');
  }
  var hour = Number(match[4]) % 12;
  if (match[7] === 'PM') hour += 12;
  return new Date(Date.UTC(Number(match[3]), monthIndex, Number(match[2]), hour - EAT_OFFSET_HOURS,
    Number(match[5]), Number(match[6])));
}

function cleanId(value) {
  return String(value).trim().toUpperCase();
}

function cleanLabel(value) {
  return String(value).trim();
}

function titleCase(value) {
  return value.replace(/\w\S*/g, function (word) {
    return word.charAt(0).toUpperCase() + word.slice(1).toLowerCase();
  });
}

function coerceNumeric(value, field) {
  var num = Number(value);
  if (value === '' || value === null || value === undefined || isNaN(num)) {
    throw new Error(field + ': non-numeric value "' + value + '"');
  }
  return num;
}

function coerceBinary(value, field) {
  if (value === '1') return true;
  if (value === '0') return false;
  throw new Error(field + ': unexpected value "' + value + '"');
}

function coerceFlag(value) {
  return value === '1';
}

function dedupeKeepLatest(rows, keyFn) {
  var latest = {};
  rows.forEach(function (row) {
    var key = keyFn(row);
    var existing = latest[key];
    if (!existing || row.submission_date > existing.submission_date) {
      latest[key] = row;
    }
  });
  return objectValues(latest);
}

function cleanDistribution(rawRecords) {
  var rows = rawRecords.map(function (raw) {
    var row = {
      unique_farmer_id: cleanId(raw.unique_farmer_id),
      country: cleanLabel(raw.country).toLowerCase(),
      region: titleCase(cleanLabel(raw.region)),
      submission_date: parseSctoDate(raw.SubmissionDate),
      seed_variety: cleanLabel(raw.seed_variety).toLowerCase(),
      variety_other: raw.variety_other || null,
      is_delivered: coerceBinary(raw.seed_delivered, 'seed_delivered'),
      quantity_kg: coerceNumeric(raw.quantity_kg, 'quantity_kg'),
      distribution_challenges: raw.distribution_challenges || null,
    };
    Object.keys(CHANNEL_COLS).forEach(function (rawCol) {
      row[CHANNEL_COLS[rawCol]] = coerceFlag(raw[rawCol]);
    });
    return row;
  });
  return dedupeKeepLatest(rows, function (row) { return row.unique_farmer_id; });
}

function cleanCropHealth(rawRecords) {
  var rows = rawRecords.map(function (raw) {
    var row = {
      unique_farmer_id: cleanId(raw.unique_farmer_id),
      country: cleanLabel(raw.country).toLowerCase(),
      region: titleCase(cleanLabel(raw.region)),
      submission_date: parseSctoDate(raw.SubmissionDate),
      growth_stage: cleanLabel(raw.growth_stage).toLowerCase(),
      plant_height_cm: coerceNumeric(raw.plant_height_cm, 'plant_height_cm'),
      has_pest_disease: coerceBinary(raw.pest_disease_present, 'pest_disease_present'),
      additional_observations: raw.additional_observations || null,
    };
    Object.keys(SYMPTOM_COLS).forEach(function (rawCol) {
      row[SYMPTOM_COLS[rawCol]] = coerceFlag(raw[rawCol]);
    });
    return row;
  });
  var deduped = dedupeKeepLatest(rows, function (row) { return row.unique_farmer_id + '|' + row.growth_stage; });
  return addHeightZWithinStage(deduped);
}

function addHeightZWithinStage(rows) {
  var byStage = {};
  rows.forEach(function (row) {
    (byStage[row.growth_stage] = byStage[row.growth_stage] || []).push(row.plant_height_cm);
  });

  var stats = {};
  Object.keys(byStage).forEach(function (stage) {
    var values = byStage[stage];
    var mean = values.reduce(function (a, b) { return a + b; }, 0) / values.length;
    var variance = values.length > 1
      ? values.reduce(function (sum, v) { return sum + Math.pow(v - mean, 2); }, 0) / (values.length - 1)
      : 0;
    stats[stage] = { mean: mean, std: Math.sqrt(variance) };
  });

  return rows.map(function (row) {
    var stat = stats[row.growth_stage];
    var z = stat.std > 0 ? (row.plant_height_cm - stat.mean) / stat.std : null;
    row.height_z_within_stage = z;
    return row;
  });
}

function buildFarmerMaster(distribution, cropHealth) {
  var distById = {};
  distribution.forEach(function (row) { distById[row.unique_farmer_id] = row; });

  var cropByFarmer = {};
  cropHealth.forEach(function (row) {
    (cropByFarmer[row.unique_farmer_id] = cropByFarmer[row.unique_farmer_id] || []).push(row);
  });

  var allIds = objectKeys(distById).concat(objectKeys(cropByFarmer))
    .filter(function (id, index, ids) { return ids.indexOf(id) === index; })
    .sort();

  return allIds.map(function (id) {
    var dist = distById[id] || null;
    var visits = (cropByFarmer[id] || []).slice().sort(function (a, b) { return a.submission_date - b.submission_date; });
    var linkStatus = dist && visits.length ? 'linked' : dist ? 'distribution_only' : 'crop_health_only';

    var cropCountries = uniqueValues(visits.map(function (v) { return v.country; }));
    var cropRegions = uniqueValues(visits.map(function (v) { return v.region; }));
    var cropCountry = visits.length ? visits[0].country : null;
    var cropRegion = visits.length ? visits[0].region : null;

    var countryMismatch = cropCountries.length > 1 || (linkStatus === 'linked' && dist.country !== cropCountry);
    var regionMismatch = cropRegions.length > 1 || (linkStatus === 'linked' && dist.region !== cropRegion);

    var firstVisit = visits.length ? visits[0] : null;
    var lastVisit = visits.length ? visits[visits.length - 1] : null;
    var daysBetweenSubmissions = dist && firstVisit
      ? Math.round((firstVisit.submission_date - dist.submission_date) / 86400000)
      : null;

    var row = {
      unique_farmer_id: id,
      link_status: linkStatus,
      country: (dist ? dist.country : null) || cropCountry,
      region: (dist ? dist.region : null) || cropRegion,
      country_mismatch: countryMismatch,
      region_mismatch: regionMismatch,
      geo_mismatch: countryMismatch || regionMismatch,
      distribution_submission_date: dist ? dist.submission_date : null,
      seed_variety: dist ? dist.seed_variety : null,
      is_delivered: dist ? dist.is_delivered : null,
      quantity_kg: dist ? dist.quantity_kg : null,
      n_crop_health_visits: visits.length,
      first_crop_health_date: firstVisit ? firstVisit.submission_date : null,
      last_crop_health_date: lastVisit ? lastVisit.submission_date : null,
      latest_growth_stage: lastVisit ? lastVisit.growth_stage : null,
      latest_plant_height_cm: lastVisit ? lastVisit.plant_height_cm : null,
      latest_height_z_within_stage: lastVisit ? lastVisit.height_z_within_stage : null,
      has_pest_disease: visits.length ? visits.some(function (v) { return v.has_pest_disease; }) : null,
      days_between_submissions: daysBetweenSubmissions,
    };
    objectValues(CHANNEL_COLS).forEach(function (col) {
      row[col] = dist ? dist[col] : null;
    });
    return row;
  });
}

function writeSheet(sheetName, rows, columns) {
  var ss = SpreadsheetApp.getActive();
  var sheet = ss.getSheetByName(sheetName) || ss.insertSheet(sheetName);
  sheet.clearContents();
  sheet.getRange(1, 1, 1, columns.length).setValues([columns]);
  if (rows.length) {
    var data = rows.map(function (row) {
      return columns.map(function (col) { return row[col] === undefined ? null : row[col]; });
    });
    sheet.getRange(2, 1, data.length, columns.length).setValues(data);
  }
}

// Reads a tab this script previously wrote back into typed row objects, so the form that was not
// refreshed this run can still take part in the farmer_master join using its last known good data.
function readSheetAsObjects(sheetName, columns) {
  var sheet = SpreadsheetApp.getActive().getSheetByName(sheetName);
  if (!sheet || sheet.getLastRow() < 2) return [];
  var values = sheet.getRange(2, 1, sheet.getLastRow() - 1, columns.length).getValues();
  return values.map(function (rowValues) {
    var row = {};
    columns.forEach(function (col, index) {
      var value = rowValues[index];
      row[col] = value === '' ? null : value;
    });
    DATE_COLUMNS.forEach(function (col) {
      if (row[col] && !(row[col] instanceof Date)) row[col] = new Date(row[col]);
    });
    return row;
  });
}

function writeMeta(refreshedFormKey, refreshedRows, duplicatesDropped, farmerMasterRows) {
  var ss = SpreadsheetApp.getActive();
  var sheet = ss.getSheetByName('meta') || ss.insertSheet('meta');
  var nowStr = Utilities.formatDate(new Date(), 'Africa/Nairobi', 'yyyy-MM-dd HH:mm:ss');

  var meta = readMetaAsMap(sheet);
  meta['last_refreshed_eat'] = nowStr;
  meta[refreshedFormKey + '_last_refreshed_eat'] = nowStr;
  meta[refreshedFormKey + '_rows'] = refreshedRows;
  meta[refreshedFormKey + '_duplicates_dropped'] = duplicatesDropped;
  meta['farmer_master_rows'] = farmerMasterRows;
  meta['source'] = 'SurveyCTO REST API, test_form_one_data_specialist_pmi and test_form_two_data_specialist_pmi';

  sheet.clearContents();
  var rows = Object.keys(meta).map(function (key) { return [key, meta[key]]; });
  sheet.getRange(1, 1, rows.length, 2).setValues(rows);
}

function readMetaAsMap(sheet) {
  if (sheet.getLastRow() < 1) return {};
  var values = sheet.getRange(1, 1, sheet.getLastRow(), 2).getValues();
  var map = {};
  values.forEach(function (row) { if (row[0]) map[row[0]] = row[1]; });
  return map;
}

function setupSpreadsheet() {
  var ss = SpreadsheetApp.getActive();
  ss.setSpreadsheetTimeZone('Africa/Nairobi');
  ['distribution', 'crop_health', 'farmer_master', 'meta'].forEach(function (name) {
    if (!ss.getSheetByName(name)) ss.insertSheet(name);
  });
  var props = PropertiesService.getScriptProperties();
  if (!props.getProperty(NEXT_FORM_PROPERTY)) props.setProperty(NEXT_FORM_PROPERTY, 'distribution');
}

function installRefreshTrigger() {
  ScriptApp.getProjectTriggers().forEach(function (trigger) {
    if (trigger.getHandlerFunction() === 'refreshDashboardData') {
      ScriptApp.deleteTrigger(trigger);
    }
  });
  ScriptApp.newTrigger('refreshDashboardData').timeBased().everyMinutes(15).create();
}

function objectKeys(obj) {
  return Object.keys(obj);
}

function objectValues(obj) {
  return Object.keys(obj).map(function (key) { return obj[key]; });
}

function uniqueValues(values) {
  return values.filter(function (value, index) { return values.indexOf(value) === index; });
}
