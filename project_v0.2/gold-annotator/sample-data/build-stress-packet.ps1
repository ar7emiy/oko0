$ErrorActionPreference = 'Stop'

# Fictional, deterministic scale packet. It is intentionally separate from any client data.
$root = Join-Path $PSScriptRoot 'stress-packet'
$notes = Join-Path $root 'notes'
New-Item -ItemType Directory -Force -Path $notes | Out-Null

$specs = @(
  [pscustomobject]@{claim='C201'; org='Northstar Orthopedics'; short='Northstar'; category='medical provider'; person='Dr. Ada Monroe'; role='orthopedic surgeon'; address='101 Alder Avenue'; city='Lakeview'; state='IL'; zip='60101'; phone='555-201-0101'; tin='STRESS-201'},
  [pscustomobject]@{claim='C202'; org='Silverline Legal'; short='Silverline'; category='legal representative'; person='Olivia Park'; role='attorney'; address='202 Birch Street'; city='Lakeview'; state='IL'; zip='60102'; phone='555-202-0102'; tin='STRESS-202'},
  [pscustomobject]@{claim='C203'; org='Meridian Imaging'; short='Meridian'; category='diagnostic provider'; person='Lee Patel'; role='imaging coordinator'; address='303 Cedar Road'; city='Lakeview'; state='IL'; zip='60103'; phone='555-203-0103'; tin='STRESS-203'},
  [pscustomobject]@{claim='C204'; org='Beacon Pharmacy'; short='Beacon'; category='pharmacy'; person='Dr. Jordan Kim'; role='pharmacist'; address='404 Dogwood Lane'; city='Lakeview'; state='IL'; zip='60104'; phone='555-204-0104'; tin='STRESS-204'},
  [pscustomobject]@{claim='C205'; org='Atlas Rehabilitation'; short='Atlas'; category='rehabilitation provider'; person='Samira Noor'; role='therapist'; address='505 Elm Drive'; city='Lakeview'; state='IL'; zip='60105'; phone='555-205-0105'; tin='STRESS-205'},
  [pscustomobject]@{claim='C206'; org='Cedar Claims Services'; short='Cedar'; category='claims administrator'; person='Gabriel Torres'; role='claim adjuster'; address='606 Fir Court'; city='Lakeview'; state='IL'; zip='60106'; phone='555-206-0106'; tin='STRESS-206'}
)

foreach ($s in $specs) {
  $texts = @(
    "$($s.person) called regarding the claim. $($s.person) is a $($s.role) with $($s.org), the $($s.category).",
    "$($s.org) sent an update. The organization requested records before it could continue the review.",
    "$($s.person) confirmed that she would send the requested documents to $($s.org).",
    "Sender: $($s.org)`n$($s.address), $($s.city), $($s.state) $($s.zip)`nPhone: $($s.phone)`nTIN: $($s.tin)",
    "$($s.short) confirmed the appointment. $($s.org) will provide the next update.",
    "A caller mentioned $($s.short) in passing. The note does not establish whether that wording refers to $($s.org) or another organization with a similar name.",
    "Administrative note: the claim packet was indexed. No person or organization is identified in this note.",
    "$($s.org) assigned $($s.person) as the $($s.role). The $($s.category) will contact the claimant.",
    "They said a response would follow. The prior discussion names both $($s.person) and $($s.org), so this reference is intentionally ambiguous.",
    "$($s.org) remains the $($s.category) for this claim. Contact details remain $($s.address), $($s.city), $($s.state) $($s.zip), $($s.phone), and $($s.tin)."
  )
  for ($i = 1; $i -le 10; $i++) {
    $noteId = 'N{0:D2}' -f $i
    Set-Content -LiteralPath (Join-Path $notes "$($s.claim)_$noteId.txt") -Value $texts[$i - 1] -Encoding utf8
  }
}

$headers = @('claim_number','recordType','entity_category_name','entity_subcategory_name','entity_name','entity_address','entity_city','entity_state','entity_zip_code','entity_phone','entity_TIN','entity_NER_tag','Entity_Watchlist_flag','Exact_search_Note_ID','Exact_search_matched_watchlist_entity_name','GenAI_search_Note_ID','GenAI_entityNameClearned','GenAI_tok_sort_similarity','Watchlist_entity_id','Watchlist_entity_name','watchlist_address','watchlist_city','watchlist_state','watchlist_zip_code','watchlist_phone','watchlist_TIN')
$rows = foreach ($s in $specs) {
  [ordered]@{claim_number=$s.claim;recordType='entity';entity_category_name=$s.category;entity_subcategory_name='';entity_name=$s.org;entity_address=$s.address;entity_city=$s.city;entity_state=$s.state;entity_zip_code=$s.zip;entity_phone=$s.phone;entity_TIN=$s.tin;entity_NER_tag='ORG';Entity_Watchlist_flag='0';Exact_search_Note_ID='';Exact_search_matched_watchlist_entity_name='';GenAI_search_Note_ID='N10';GenAI_entityNameClearned=$s.org;GenAI_tok_sort_similarity='';Watchlist_entity_id='';Watchlist_entity_name='';watchlist_address='';watchlist_city='';watchlist_state='';watchlist_zip_code='';watchlist_phone='';watchlist_TIN=''}
  [ordered]@{claim_number=$s.claim;recordType='genai_only';entity_category_name=$s.category;entity_subcategory_name='';entity_name=$s.person;entity_address='';entity_city='';entity_state='';entity_zip_code='';entity_phone='';entity_TIN='';entity_NER_tag='PERSON';Entity_Watchlist_flag='1';Exact_search_Note_ID='';Exact_search_matched_watchlist_entity_name='';GenAI_search_Note_ID='N08';GenAI_entityNameClearned=$s.person;GenAI_tok_sort_similarity='96';Watchlist_entity_id="WL-$($s.claim)";Watchlist_entity_name=$s.person;watchlist_address='';watchlist_city='';watchlist_state='';watchlist_zip_code='';watchlist_phone='';watchlist_TIN=''}
}
$rows | ForEach-Object { [pscustomobject]$_ } | Select-Object $headers | Export-Csv -LiteralPath (Join-Path $root 'client-export.csv') -NoTypeInformation -Encoding utf8

@'
# 60-note fictional stress packet

This packet contains six fictional claims with ten UTF-8 notes each. It exercises repeated full names, shortened organization forms, pronouns, organization descriptions, contact fields, no-entity notes, and deliberately ambiguous references. It is suitable for loading and interaction/scale testing; it is not Gold truth.

Load every file in `notes`, then optionally load `client-export.csv` only after testing independent Gold annotation.
'@ | Set-Content -LiteralPath (Join-Path $root 'README.md') -Encoding utf8

Write-Host "Created 60 fictional notes at $notes"
