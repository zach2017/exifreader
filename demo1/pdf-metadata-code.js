/**
 * PDF.js Metadata Extraction - Code Examples
 * Works completely offline with local pdf.min.js and pdf.worker.min.js
 */

// ============================================
// SETUP (required before any PDF operations)
// ============================================
pdfjsLib.GlobalWorkerOptions.workerSrc = 'pdf.worker.min.js';


// ============================================
// METHOD 1: Get All Metadata
// ============================================
async function getAllMetadata(pdfSource) {
  // pdfSource can be: URL, Uint8Array, or ArrayBuffer
  const pdf = await pdfjsLib.getDocument(pdfSource).promise;
  const metadata = await pdf.getMetadata();
  
  return {
    // Standard document info
    info: metadata.info,
    
    // XMP metadata (if present)
    xmp: metadata.metadata ? metadata.metadata.getAll() : null,
    
    // Content disposition filename
    filename: metadata.contentDispositionFilename,
    
    // Page count
    pageCount: pdf.numPages,
    
    // Document fingerprints (unique IDs)
    fingerprints: pdf.fingerprints
  };
}


// ============================================
// METHOD 2: Get Specific Fields
// ============================================
async function getBasicInfo(pdfSource) {
  const pdf = await pdfjsLib.getDocument(pdfSource).promise;
  const { info } = await pdf.getMetadata();
  
  return {
    title: info.Title || 'Untitled',
    author: info.Author || 'Unknown',
    subject: info.Subject || '',
    keywords: info.Keywords || '',
    creator: info.Creator || '',      // App that created original
    producer: info.Producer || '',    // App that made PDF
    creationDate: info.CreationDate,
    modificationDate: info.ModDate,
    pdfVersion: info.PDFFormatVersion,
    pageCount: pdf.numPages
  };
}


// ============================================
// METHOD 3: Get Custom Metadata Fields
// ============================================
async function getCustomMetadata(pdfSource) {
  const pdf = await pdfjsLib.getDocument(pdfSource).promise;
  const { info, metadata } = await pdf.getMetadata();
  
  // Standard fields to exclude
  const standardFields = [
    'Title', 'Author', 'Subject', 'Keywords', 'Creator', 'Producer',
    'CreationDate', 'ModDate', 'Trapped', 'PDFFormatVersion',
    'IsLinearized', 'IsAcroFormPresent', 'IsXFAPresent', 
    'IsCollectionPresent', 'IsSignaturesPresent'
  ];
  
  const customFields = {};
  
  // Extract non-standard fields from info dict
  for (const [key, value] of Object.entries(info || {})) {
    if (!standardFields.includes(key) && value !== undefined) {
      customFields[key] = value;
    }
  }
  
  // Also get XMP custom fields if available
  if (metadata) {
    const xmpData = metadata.getAll();
    // XMP often has namespaced keys like dc:creator, xmp:CreateDate
    for (const [key, value] of Object.entries(xmpData || {})) {
      if (!standardFields.some(f => key.toLowerCase().includes(f.toLowerCase()))) {
        customFields[`xmp:${key}`] = value;
      }
    }
  }
  
  return customFields;
}


// ============================================
// METHOD 4: Check Document Features
// ============================================
async function getDocumentFeatures(pdfSource) {
  const pdf = await pdfjsLib.getDocument(pdfSource).promise;
  const { info } = await pdf.getMetadata();
  
  return {
    hasAcroForms: info.IsAcroFormPresent || false,
    hasXFAForms: info.IsXFAPresent || false,
    isCollection: info.IsCollectionPresent || false,
    hasSignatures: info.IsSignaturesPresent || false,
    isLinearized: info.IsLinearized || false,  // "Fast web view"
    isEncrypted: pdf.loadingParams?.password !== undefined
  };
}


// ============================================
// USAGE EXAMPLES
// ============================================

// Example 1: From file input
document.getElementById('fileInput').addEventListener('change', async (e) => {
  const file = e.target.files[0];
  const arrayBuffer = await file.arrayBuffer();
  
  const metadata = await getAllMetadata({ data: arrayBuffer });
  console.log('All metadata:', metadata);
  
  const custom = await getCustomMetadata({ data: arrayBuffer });
  console.log('Custom fields:', custom);
});


// Example 2: From URL (same-origin or CORS-enabled)
async function loadFromUrl() {
  const metadata = await getAllMetadata('document.pdf');
  console.log(metadata);
}


// Example 3: Parse PDF date string
function parsePdfDate(dateStr) {
  // PDF date format: D:YYYYMMDDHHmmSS+HH'mm' or D:YYYYMMDDHHmmSS-HH'mm'
  if (!dateStr) return null;
  
  const match = dateStr.match(
    /D:(\d{4})(\d{2})(\d{2})(\d{2})?(\d{2})?(\d{2})?([+-Z])?(\d{2})?'?(\d{2})?/
  );
  
  if (!match) return null;
  
  const [, year, month, day, hour = '00', min = '00', sec = '00', tz, tzHour, tzMin] = match;
  
  let isoString = `${year}-${month}-${day}T${hour}:${min}:${sec}`;
  
  if (tz === 'Z') {
    isoString += 'Z';
  } else if (tz && tzHour) {
    isoString += `${tz}${tzHour}:${tzMin || '00'}`;
  }
  
  return new Date(isoString);
}


// ============================================
// WHAT METADATA IS AVAILABLE
// ============================================
/*
STANDARD INFO DICTIONARY FIELDS:
- Title        : Document title
- Author       : Who wrote it
- Subject      : Document subject/description
- Keywords     : Searchable keywords
- Creator      : Application that created the original (e.g., "Microsoft Word")
- Producer     : Application that made the PDF (e.g., "Adobe PDF Library")
- CreationDate : When created (D:YYYYMMDDHHmmSS format)
- ModDate      : When last modified
- Trapped      : Trapping status (True/False/Unknown)

PDF.JS ADDED FIELDS:
- PDFFormatVersion   : PDF version (e.g., "1.7")
- IsLinearized       : Optimized for web
- IsAcroFormPresent  : Has fillable forms
- IsXFAPresent       : Has XFA forms (dynamic)
- IsCollectionPresent: Is a PDF portfolio
- IsSignaturesPresent: Has digital signatures

XMP METADATA (if present):
- Can contain any custom fields
- Often has dc:* (Dublin Core), xmp:*, pdf:* namespaces
- Access via metadata.getAll() or metadata.get('fieldname')

CUSTOM FIELDS:
- Any non-standard key in the info dictionary
- Often used for document management systems
- Examples: "DocumentID", "ProjectName", "Classification", etc.
*/
