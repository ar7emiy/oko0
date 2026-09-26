# %% [markdown]
# ## Synthetic data
#
# A fictional test set with a truth file, deterministic under the run seed.
#
# * **Universe**: persons and businesses with canonical details; names drawn with Census and
#   SSA frequencies (so "Smith" is as common as it is), every identifier fictional and valid
#   (NPIs pass Luhn, VINs their check digit).
# * **Watchlist rows**: 60% of the universe, lightly noised, ~10% listed twice (watchlist
#   duplicates), plus watchlist-only parties up to the requested size.
# * **Extracted rows**: 70% of the universe (so 40% of them are not listed), null-heavy, noised
#   with the simulation table at half its rates, many parties in several claims (unmerged
#   duplicates), grouped into claims and notes.
# * **Edge cases**: ~45 hand-written cases with the expected best watchlist row, basis, veto
#   and levels, listed in the table `EDGE_CASES`.
#
# Truth is written beside the inputs and read only by diagnostics and self-tests, never by the
# pipeline (AGENTS rule 13).
#
# **Where Splink would do better.** Splink ships labelled demo datasets (febrl, historical
# persons) with known truth; they are real benchmarks. This set is ours and shaped by our own
# noise table, so results on it show that the code does what it says, not how well it would do
# on client data.

# %%
from wlink.core import *
from wlink.core import _undot, _DBA_RE, _VIN_MAP, _VIN_W, _words
from wlink.config import *
from wlink.load import *
from wlink.simulate import *


def blank_row(rid, **kw):
    r = {c: "" for c in SCHEMA}
    r["record_id"] = rid
    r.update({k: ("" if v is None else str(v)) for k, v in kw.items()})
    return r


def _npi(n):
    return luhn_npi(f"19{n:07d}")


def _ssn(n):
    return f"{200 + n % 600:03d}{10 + n % 80:02d}{1000 + n:04d}"


def _tin(n):
    return f"45{n:07d}"


def _addr(num, street, stype, city, state, zp, unit=""):
    return {"street_number": num, "street_name": street, "street_type": stype, "unit": unit,
            "city": city, "state": state, "zip": zp}


A_NY = _addr("118", "ORCHARD", "ST", "BROOKLYN", "NY", "11211")
A_NY2 = _addr("42", "HERON", "AVE", "QUEENS", "NY", "11354")
A_CA = _addr("901", "SUNSET", "BLVD", "LOS ANGELES", "CA", "90026")
A_IL = _addr("77", "CANAL", "ST", "CHICAGO", "IL", "60606", "4")
A_FL = _addr("3100", "BAYVIEW", "DR", "MIAMI", "FL", "33133")


def edge_cases():
    """Hand-written cases: (case, description, extracted rows, watchlist rows, expectations).
    An expectation names the extracted party (record_id, part), the watchlist record expected
    to be its best candidate (rank 1) or merely visible, and the basis / veto / levels."""
    C = []

    def case(cid, desc, x, w, expect):
        C.append({"case": cid, "desc": desc, "x": x, "w": w, "expect": expect})

    E = lambda **k: k
    case("E01", "person + business on one row, both identifier-linked",
         [blank_row("E01X", claim_id="CE01", note_id="NE01", first_name="Harold", last_name="Vantongeren",
                    provider_npi=_npi(101), business_name="Vantongeren Chiropractic PC", tin=_tin(101), **A_NY)],
         [blank_row("E01W1", first_name="Harold", last_name="Vantongeren", provider_npi=_npi(101), dob="1961-03-14", **A_NY),
          blank_row("E01W2", business_name="Vantongeren Chiropractic P.C.", tin=_tin(101), **A_NY)],
         [E(x="E01X", part="person", w="E01W1", basis="identifier", rank=1),
          E(x="E01X", part="business", w="E01W2", basis="identifier", rank=1)])
    case("E02", "a TIN shared by two businesses in the extracted file",
         [blank_row("E02X1", claim_id="CE02", note_id="NE02", business_name="Silverline Medical Supply", tin=_tin(102)),
          blank_row("E02X2", claim_id="CE02", note_id="NE02b", business_name="Quillfeather Diagnostics", tin=_tin(102))],
         [blank_row("E02W", business_name="Silverline Medical Supply Inc", tin=_tin(102), **A_FL)],
         [E(x="E02X1", part="business", w="E02W", basis="identifier", rank=1),
          E(x="E02X2", part="business", w="E02W", basis="identifier")])
    case("E03", "sibling companies: a shared head word, distinctive words on both sides",
         [blank_row("E03X", claim_id="CE03", note_id="NE03", business_name="Allport Indemnity Company", **A_NY2)],
         [blank_row("E03W1", business_name="Allport Indemnity Co"),
          blank_row("E03W2", business_name="Allport Casualty Surety Company", **A_NY)],
         [E(x="E03X", part="business", w="E03W1", rank=1, levels={"org": "exact"}),
          E(x="E03X", part="business", w="E03W2", levels={"org": "sibling"}, if_visible=True)])
    s4 = _ssn(104)
    case("E04", "one SSN under three names in the extracted file",
         [blank_row("E04X1", claim_id="CE04", note_id="NE04", first_name="Rosalind", last_name="Achterberg", ssn=s4),
          blank_row("E04X2", claim_id="CE04", note_id="NE04", first_name="Tobias", last_name="Wenceslas", ssn=s4),
          blank_row("E04X3", claim_id="CE04b", note_id="NE04b", first_name="Imelda", last_name="Fairweather", ssn=s4)],
         [blank_row("E04W", first_name="Rosalind", last_name="Achterberg", ssn=s4, dob="1970-02-02")],
         [E(x="E04X1", part="person", w="E04W", basis="identifier", rank=1),
          E(x="E04X2", part="person", w="E04W", basis="identifier")])
    case("E05", "junk SSN on both sides is never an identifier",
         [blank_row("E05X", claim_id="CE05", note_id="NE05", first_name="Gertrude", last_name="Oyelaran", ssn="123-45-6789", dob="1958-07-21")],
         [blank_row("E05W", first_name="Gertrude", last_name="Oyelaran", ssn="123456789", dob="1958-07-21")],
         [E(x="E05X", part="person", w="E05W", basis="dob", rank=1, levels={"ssn": "empty"})])
    case("E06", "two different single-holder SSNs veto",
         [blank_row("E06X", claim_id="CE06", note_id="NE06", first_name="Mortimer", last_name="Quackenbush", ssn=_ssn(106), dob="1966-11-02")],
         [blank_row("E06W", first_name="Mortimer", last_name="Quackenbush", ssn=_ssn(206), dob="1966-11-02")],
         [E(x="E06X", part="person", w="E06W", veto="ssn")])
    case("E07", "Bill meets William",
         [blank_row("E07X", claim_id="CE07", note_id="NE07", first_name="Bill", last_name="Szczepanski", dob="1972-05-30")],
         [blank_row("E07W", first_name="William", last_name="Szczepanski", dob="1972-05-30")],
         [E(x="E07X", part="person", w="E07W", basis="dob", rank=1, levels={"name": "first_nick_or_close"})])
    case("E08", "first-name typo, same address",
         [blank_row("E08X", claim_id="CE08", note_id="NE08", first_name="Jonathon", last_name="Kowalczyk", **A_NY2)],
         [blank_row("E08W", first_name="Jonathan", last_name="Kowalczyk", **A_NY2)],
         [E(x="E08X", part="person", w="E08W", basis="address", rank=1, levels={"address": "exact"})])
    case("E09", "first and last swapped",
         [blank_row("E09X", claim_id="CE09", note_id="NE09", first_name="Nwachukwu", last_name="Chidiebere", dob="1980-01-19")],
         [blank_row("E09W", first_name="Chidiebere", last_name="Nwachukwu", dob="1980-01-19")],
         [E(x="E09X", part="person", w="E09W", basis="dob", rank=1, levels={"name": "swapped"})])
    case("E10", "initial only, owned phone agrees",
         [blank_row("E10X", claim_id="CE10", note_id="NE10", first_name="R.", last_name="Featherstonehaugh", home_phone="(718) 392-4410")],
         [blank_row("E10W", first_name="Rupert", last_name="Featherstonehaugh", home_phone="7183924410")],
         [E(x="E10X", part="person", w="E10W", basis="identifier", rank=1, levels={"name": "initial_agrees", "phone": "exact_owned_single"})])
    case("E11", "a claim row with only a TIN",
         [blank_row("E11X", claim_id="CE11", note_id="NE11", tin=_tin(111))],
         [blank_row("E11W", business_name="Marchetti Towing LLC", tin=_tin(111), **A_NY)],
         [E(x="E11X", part="business", w="E11W", basis="identifier", rank=1)])
    case("E12", "a rare exact name and nothing else: visible as name_only",
         [blank_row("E12X", claim_id="CE12", note_id="NE12", first_name="Evangelina", last_name="Throckmorton")],
         [blank_row("E12W", first_name="Evangelina", last_name="Throckmorton", dob="1949-09-09", **A_CA)],
         [E(x="E12X", part="person", w="E12W", basis="name_only", rank=1)])
    case("E13", "John Smith and nothing else: every John Smith visible, name_only",
         [blank_row("E13X", claim_id="CE13", note_id="NE13", first_name="John", last_name="Smith")],
         [blank_row(f"E13W{i}", first_name="John", last_name="Smith", dob=f"19{50 + i}-01-0{i}") for i in (1, 2, 3)],
         [E(x="E13X", part="person", w=f"E13W{i}", basis="name_only") for i in (1, 2, 3)])
    case("E14", "day and month swapped",
         [blank_row("E14X", claim_id="CE14", note_id="NE14", first_name="Philippa", last_name="Gundersen", dob="1975-04-09")],
         [blank_row("E14W", first_name="Philippa", last_name="Gundersen", dob="1975-09-04")],
         [E(x="E14X", part="person", w="E14W", basis="dob", rank=1, levels={"dob": "swap_or_typo"})])
    case("E15", "moved to another state, SSN agrees",
         [blank_row("E15X", claim_id="CE15", note_id="NE15", first_name="Cornelius", last_name="Abernethy", ssn=_ssn(115), **A_NY)],
         [blank_row("E15W", first_name="Cornelius", last_name="Abernethy", ssn=_ssn(115), **A_CA)],
         [E(x="E15X", part="person", w="E15W", basis="identifier", rank=1, levels={"address": "differs"})])
    case("E16", "given category conflicts with an NPI",
         [blank_row("E16X", claim_id="CE16", note_id="NE16", category="legal", first_name="Winifred", last_name="Castellano", provider_npi=_npi(116))],
         [blank_row("E16W", first_name="Winifred", last_name="Castellano", provider_npi=_npi(116))],
         [E(x="E16X", part="person", w="E16W", basis="identifier", rank=1, party={"category_mismatch": True, "category": "medical"})])
    case("E17", "keyword business: repair shop",
         [blank_row("E17X", claim_id="CE17", note_id="NE17", business_name="Ramirez Auto Body & Collision")],
         [blank_row("E17W", business_name="Ramirez Auto Body and Collision Inc")],
         [E(x="E17X", part="business", w="E17W", rank=1, levels={"org": "exact"},
            party={"category_inferred": "repair shop"})])
    v18 = vin_with_check("1FTFW1E5JFA12345", None)
    case("E18", "VIN agrees",
         [blank_row("E18X", claim_id="CE18", note_id="NE18", first_name="Desmond", last_name="Okonkwo-Lind", vin=v18)],
         [blank_row("E18W", first_name="Desmond", last_name="Okonkwo-Lind", vin=v18)],
         [E(x="E18X", part="person", w="E18W", basis="identifier", rank=1)])
    case("E19", "a clinic phone shared by two doctors is not an identifier",
         [blank_row("E19X1", claim_id="CE19", note_id="NE19", first_name="Anneliese", last_name="Borowczyk", work_phone="3124640199", business_name="Northgate Spine Center"),
          blank_row("E19X2", claim_id="CE19", note_id="NE19", first_name="Tiberius", last_name="Maclean", work_phone="312-464-0199", business_name="Northgate Spine Center")],
         [blank_row("E19W", first_name="Anneliese", last_name="Borowczyk", work_phone="3124640199")],
         [E(x="E19X2", part="person", w="E19W", basis_not="identifier", levels={"phone": "exact_shared"})])
    case("E20", "co-party: the tied businesses share a TIN",
         [blank_row("E20X", claim_id="CE20", note_id="NE20", first_name="Leopold", last_name="Anyanwu", business_name="Anyanwu Family Medicine PC", tin=_tin(120))],
         [blank_row("E20W", first_name="Leopold", last_name="Anyanwu", business_name="Anyanwu Family Medicine PC", tin=_tin(120))],
         [E(x="E20X", part="business", w="E20W", basis="identifier", rank=1),
          E(x="E20X", part="person", w="E20W", basis="co_party", rank=1, levels={"co_party": "anchored"})])
    case("E21", "co-party needs an anchor: name-only businesses vouch for nothing",
         [blank_row("E21X", claim_id="CE21", note_id="NE21", first_name="Octavia", last_name="Pellegrini", business_name="Pellegrini Wellness")],
         [blank_row("E21W", first_name="Octavia", last_name="Pellegrini", business_name="Pellegrini Wellness")],
         [E(x="E21X", part="person", w="E21W", basis="name_only", rank=1)])
    case("E22", "watchlist duplicates: the same person listed twice",
         [blank_row("E22X", claim_id="CE22", note_id="NE22", first_name="Ingrid", last_name="Solberg-Haas", provider_npi=_npi(122))],
         [blank_row("E22W1", first_name="Ingrid", last_name="Solberg-Haas", provider_npi=_npi(122), **A_IL),
          blank_row("E22W2", first_name="Ingrid", last_name="Solberg Haas", provider_npi=_npi(122), **A_FL)],
         [E(x="E22X", part="person", w="E22W1", basis="identifier", true=True),
          E(x="E22X", part="person", w="E22W2", basis="identifier", true=True)])
    case("E23", "an invalid NPI is never an identifier",
         [blank_row("E23X", claim_id="CE23", note_id="NE23", first_name="Fenwick", last_name="Oduya", provider_npi="1234567890")],
         [blank_row("E23W", first_name="Fenwick", last_name="Oduya", provider_npi="1234567890")],
         [E(x="E23X", part="person", w="E23W", basis="name_only", rank=1, levels={"npi": "empty"})])
    case("E24", "an empty row yields no party and is reported",
         [blank_row("E24X", claim_id="CE24", note_id="NE24", city="BROOKLYN")], [],
         [E(x="E24X", part="none", empty_row=True)])
    case("E25", "one part of a compound surname dropped",
         [blank_row("E25X", claim_id="CE25", note_id="NE25", first_name="Maria", last_name="Garcia-Villanueva", dob="1983-06-17")],
         [blank_row("E25W", first_name="Maria", last_name="Garcia", dob="1983-06-17")],
         [E(x="E25X", part="person", w="E25W", basis="dob", rank=1, levels={"name": "last_close_first_agrees"})])
    case("E26", "surname changed, SSN and DOB agree",
         [blank_row("E26X", claim_id="CE26", note_id="NE26", first_name="Beatrix", last_name="Holloway", ssn=_ssn(126), dob="1979-12-01")],
         [blank_row("E26W", first_name="Beatrix", last_name="Lindqvist", ssn=_ssn(126), dob="1979-12-01")],
         [E(x="E26X", part="person", w="E26W", basis="identifier", rank=1, levels={"name": "else"})])
    case("E27", "two driver licences of one state veto",
         [blank_row("E27X", claim_id="CE27", note_id="NE27", first_name="Casimir", last_name="Vandermeer", driver_license_number="D2700001", driver_license_state="NY")],
         [blank_row("E27W", first_name="Casimir", last_name="Vandermeer", driver_license_number="K5839204", driver_license_state="NY")],
         [E(x="E27X", part="person", w="E27W", veto="dl")])
    case("E28", "driver licences of two states do not veto",
         [blank_row("E28X", claim_id="CE28", note_id="NE28", first_name="Rosamund", last_name="Ekwueme", driver_license_number="D2800001", driver_license_state="NY")],
         [blank_row("E28W", first_name="Rosamund", last_name="Ekwueme", driver_license_number="E2800002", driver_license_state="NJ")],
         [E(x="E28X", part="person", w="E28W", veto="", rank=1)])
    case("E29", "email agrees",
         [blank_row("E29X", claim_id="CE29", note_id="NE29", first_name="Thaddeus", last_name="Blackwood", email="T.Blackwood@Mailbox.test")],
         [blank_row("E29W", first_name="Thaddeus", last_name="Blackwood", email="t.blackwood@mailbox.test")],
         [E(x="E29X", part="person", w="E29W", basis="identifier", rank=1)])
    case("E30", "a placeholder DOB is no evidence",
         [blank_row("E30X", claim_id="CE30", note_id="NE30", first_name="Ottoline", last_name="Ferrante", dob="1900-01-01")],
         [blank_row("E30W", first_name="Ottoline", last_name="Ferrante", dob="01/01/1900")],
         [E(x="E30X", part="person", w="E30W", basis="name_only", rank=1, levels={"dob": "empty"})])
    case("E31", "middle initials differ, DOB agrees",
         [blank_row("E31X", claim_id="CE31", note_id="NE31", first_name="Lucius", middle_name="J", last_name="Harrowgate", dob="1964-08-08")],
         [blank_row("E31W", first_name="Lucius", middle_name="K", last_name="Harrowgate", dob="1964-08-08")],
         [E(x="E31X", part="person", w="E31W", basis="dob", rank=1, levels={"middle": "differs"})])
    case("E32", "the trade name of a declared d/b/a",
         [blank_row("E32X", claim_id="CE32", note_id="NE32", business_name="Kestrel Imaging LLC d/b/a Harborview Radiology")],
         [blank_row("E32W", business_name="Harborview Radiology")],
         [E(x="E32X", part="business", w="E32W", rank=1, levels={"org": "exact"})])
    case("E33", "a d/b/a declared by another record",
         [blank_row("E33X", claim_id="CE33", note_id="NE33", business_name="Tamarind Wellness Group"),
          blank_row("E33D", claim_id="CE33b", note_id="NE33b", business_name="Juniper Holistic Center d/b/a Tamarind Wellness Group")],
         [blank_row("E33W", business_name="Juniper Holistic Center")],
         [E(x="E33X", part="business", w="E33W", levels={"org": "dba"}, true=True)])
    case("E34", "abbreviations expanded",
         [blank_row("E34X", claim_id="CE34", note_id="NE34", business_name="Lakeshore Med Ctr")],
         [blank_row("E34W", business_name="Lakeshore Medical Center Inc")],
         [E(x="E34X", part="business", w="E34W", rank=1, levels={"org": "exact"})])
    case("E35", "a short form of the name",
         [blank_row("E35X", claim_id="CE35", note_id="NE35", business_name="Pinecrest Orthopedic")],
         [blank_row("E35W", business_name="Pinecrest Orthopedic Rehabilitation")],
         [E(x="E35X", part="business", w="E35W", rank=1, levels={"org": "short_form"})])
    case("E36", "name plus city and specialty: contextual",
         [blank_row("E36X", claim_id="CE36", note_id="NE36", first_name="Ignatius", last_name="Wojciechowski", provider_specialty="Chiropractor", city="Chicago", state="IL")],
         [blank_row("E36W", first_name="Ignatius", last_name="Wojciechowski", provider_specialty="CHIROPRACTIC", city="CHICAGO", state="IL")],
         [E(x="E36X", part="person", w="E36W", basis="contextual", rank=1)])
    s37 = _ssn(137)
    s37n = s37[:4] + str((int(s37[4]) + 1) % 10) + s37[5:]
    case("E37", "one SSN digit mistyped: near, no veto",
         [blank_row("E37X", claim_id="CE37", note_id="NE37", first_name="Serafina", last_name="Lindgren", ssn=s37n, dob="1990-03-03")],
         [blank_row("E37W", first_name="Serafina", last_name="Lindgren", ssn=s37, dob="1990-03-03")],
         [E(x="E37X", part="person", w="E37W", veto="", rank=1, levels={"ssn": "near"})])
    s38 = _ssn(138)
    s38t = s38[:6] + s38[7] + s38[6] + s38[8:]
    case("E38", "two SSN digits transposed: near, no veto",
         [blank_row("E38X", claim_id="CE38", note_id="NE38", first_name="Augustin", last_name="Merriweather", ssn=s38t, dob="1955-10-10")],
         [blank_row("E38W", first_name="Augustin", last_name="Merriweather", ssn=s38, dob="1955-10-10")],
         [E(x="E38X", part="person", w="E38W", veto="", rank=1, levels={"ssn": "near"})])
    case("E39", "a claim row with only a clinic NPI",
         [blank_row("E39X", claim_id="CE39", note_id="NE39", clinic_npi=_npi(139))],
         [blank_row("E39W", business_name="Harbor Point Physical Therapy", clinic_npi=_npi(139))],
         [E(x="E39X", part="business", w="E39W", basis="identifier", rank=1)])
    case("E40", "surname only, DOB agrees",
         [blank_row("E40X", claim_id="CE40", note_id="NE40", last_name="Quintanilla-Obi", dob="1987-02-25")],
         [blank_row("E40W", first_name="Esperanza", last_name="Quintanilla-Obi", dob="1987-02-25")],
         [E(x="E40X", part="person", w="E40W", basis="dob", rank=1, levels={"name": "first_empty"})])
    case("E41", "LLP: keyword legal",
         [blank_row("E41X", claim_id="CE41", note_id="NE41", business_name="Pemberton & Vasquez LLP")], [],
         [E(x="E41X", part="business", party={"category_inferred": "legal"})])
    case("E42", "a witness is a private party",
         [blank_row("E42X", claim_id="CE42", note_id="NE42", category="witness", first_name="Jeremiah", last_name="Tolliver")], [],
         [E(x="E42X", part="person", party={"prior_group": "private"})])
    case("E43", "one NPI under two different names: identifier basis, the names count against",
         [blank_row("E43X", claim_id="CE43", note_id="NE43", first_name="Alice", last_name="Brennan-Yoo", provider_npi=_npi(143))],
         [blank_row("E43W", first_name="Marcus", last_name="Delacroix-Ibe", provider_npi=_npi(143))],
         [E(x="E43X", part="person", w="E43W", basis="identifier", veto="")])
    case("E44", "licence plate agrees",
         [blank_row("E44X", claim_id="CE44", note_id="NE44", first_name="Horatio", last_name="Villalobos", plate_number="HVX 4412", plate_state="NY")],
         [blank_row("E44W", first_name="Horatio", last_name="Villalobos", plate_number="HVX4412", plate_state="NY")],
         [E(x="E44X", part="person", w="E44W", basis="identifier", rank=1)])
    case("E45", "professional licence agrees; licence type makes it medical",
         [blank_row("E45X", claim_id="CE45", note_id="NE45", first_name="Clementine", last_name="Arbuthnot", professional_license_number="045678", professional_license_state="NY", professional_license_type="DC")],
         [blank_row("E45W", first_name="Clementine", last_name="Arbuthnot", professional_license_number="45678", professional_license_state="NY")],
         [E(x="E45X", part="person", party={"category": "medical", "prior_group": "professional"})])
    return C


def _person_entity(fake, rng, eid, professional):
    first, last = str(fake.first()), str(fake.surname())
    if rng.random() < 0.08:
        last = f"{last}-{fake.surname()}"
    e = {"eid": eid, "kind": "person", "first_name": first.title(), "last_name": last.title(),
         "middle_name": str(fake.first()).title() if rng.random() < 0.6 else "",
         "dob": fake.dob(), "ssn": fake.ssn(), "home_phone": fake.phone(),
         "driver_license_number": fake.dl(), "email": fake.email(first, last)}
    a = fake.address()
    e.update(a)
    e["driver_license_state"] = a["state"]
    if rng.random() < 0.2:
        e["vin"] = fake.vin(); e["plate_number"] = fake.plate(); e["plate_state"] = a["state"]
    if professional:
        spec = str(rng.choice(SPECIALTIES))
        e.update({"provider_npi": fake.npi(), "professional_license_number": fake.digits(6),
                  "professional_license_state": a["state"], "provider_specialty": spec,
                  "category": "medical", "work_phone": fake.phone()})
        if rng.random() < 0.08:
            e.update({"category": "legal", "provider_npi": "", "provider_specialty": "",
                      "professional_license_type": "ATTORNEY"})
    else:
        e["category"] = str(rng.choice(["claimant", "witness", "claimant"]))
    return e


BUSINESS_KINDS = [("Medical", "PC", "medical"), ("Chiropractic", "PC", "medical"),
                  ("Physical Therapy", "PLLC", "medical"), ("Imaging", "LLC", "medical"),
                  ("Acupuncture", "PC", "medical"), ("Rehabilitation Center", "Inc", "medical"),
                  ("Pharmacy", "Inc", "medical"), ("Auto Body", "Inc", "repair shop"),
                  ("Collision", "LLC", "repair shop"), ("Towing", "Corp", "repair shop"),
                  ("Law Offices", "PC", "legal"), ("Legal Group", "LLP", "legal"),
                  ("Diagnostics", "LLC", "medical"), ("Orthopedic Associates", "PC", "medical")]


def _business_entity(fake, rng, eid):
    kind, suffix, cat = BUSINESS_KINDS[int(rng.integers(0, len(BUSINESS_KINDS)))]
    head = str(fake.surname()).title()
    if rng.random() < 0.3:                       # 'Maple Ridge Kowalski ...': not only a surname
        head = f"{str(rng.choice(STREET_NAMES)).title()} {head}"
    name = f"{head} {kind} {suffix}"
    if kind == "Law Offices":
        name = f"Law Offices of {str(fake.first()).title()} {head}"
    if rng.random() < 0.08:
        name = f"{name} d/b/a {str(rng.choice(STREET_NAMES)).title()} {kind}"
    e = {"eid": eid, "kind": "business", "business_name": name, "tin": fake.tin(),
         "work_phone": fake.phone(), "email": f"office{int(rng.integers(1, 99999))}@{head.lower()}.test",
         "category": cat}
    if cat == "medical":
        e["clinic_npi"] = fake.npi()
    e.update(fake.address())
    return e


W_KEEP = {"dob": 0.9, "ssn": 0.3, "provider_npi": 0.9, "clinic_npi": 0.8, "tin": 0.5, "home_phone": 0.4,
          "work_phone": 0.5, "email": 0.2, "driver_license_number": 0.2, "professional_license_number": 0.5,
          "vin": 0.3, "street_name": 0.95, "provider_specialty": 0.9, "category": 0.0, "middle_name": 0.7}
X_KEEP = {"dob": 0.55, "ssn": 0.25, "provider_npi": 0.6, "clinic_npi": 0.5, "tin": 0.5, "home_phone": 0.4,
          "work_phone": 0.3, "email": 0.25, "driver_license_number": 0.2, "professional_license_number": 0.3,
          "vin": 0.3, "street_name": 0.6, "provider_specialty": 0.5, "category": 0.7, "middle_name": 0.5}
_GROUPS = {"street_name": ["street_number", "street_direction", "street_name", "street_type", "unit", "zip"],
           "driver_license_number": ["driver_license_number", "driver_license_state"],
           "professional_license_number": ["professional_license_number", "professional_license_state"],
           "vin": ["vin", "plate_number", "plate_state"]}


def _thin(r, keep, rng):
    for k, p in keep.items():
        if rng.random() >= p:
            for c in _GROUPS.get(k, [k]):
                r[c] = ""
    return r


def _row_from(entities, rid, keep, rng):
    r = blank_row(rid)
    for e in entities:
        for k, v in e.items():
            if k in r and v and (not r[k] or k not in ("category",)):
                r[k] = v
    return _thin(r, keep, rng)


def make_dataset(n_persons, n_businesses, n_watchlist, ref, noise, seed, x_share=0.75, w_share=0.6,
                 w_dup=0.1, x_repeat=0.5, x_noise_scale=0.5, w_noise_scale=0.15, include_edges=True,
                 prefix="S"):
    """(extracted rows, watchlist rows, truth pairs, edge cases). Truth pairs are
    (extracted record_id, part, watchlist record_id) for the same entity and part."""
    rng = np.random.default_rng(seed)
    fake = Fake(ref, rng)
    persons = [_person_entity(fake, rng, f"{prefix}P{i}", rng.random() < 0.35) for i in range(n_persons)]
    biz = [_business_entity(fake, rng, f"{prefix}B{i}") for i in range(n_businesses)]
    owner = {}                                  # business -> professional person on the same rows
    profs = [p for p in persons if p.get("provider_npi") or p.get("professional_license_type")]
    for b in biz:
        if profs and rng.random() < 0.4:
            owner[b["eid"]] = profs[int(rng.integers(0, len(profs)))]
    owners = {o["eid"] for o in owner.values()}
    units = [[p] for p in persons if p["eid"] not in owners]
    units += [[b, owner[b["eid"]]] if b["eid"] in owner else [b] for b in biz]
    w_rows, x_rows, w_ent, x_ent = [], [], [], []
    for u in units:
        if rng.random() < w_share:
            for k in range(2 if rng.random() < w_dup else 1):
                rid = f"{prefix}W{len(w_rows):06d}"
                r = _row_from(u, rid, W_KEEP, rng)
                r["category"] = ""
                if k == 1:
                    r.update(fake.address(r.get("state") or None))
                w_rows.append(r); w_ent.append([e["eid"] for e in u])
        if rng.random() < x_share:
            for k in range(1 + int(rng.random() < x_repeat) + int(rng.random() < x_repeat / 3)):
                rid = f"{prefix}X{len(x_rows):06d}"
                x_rows.append(_row_from(u, rid, X_KEEP, rng)); x_ent.append([e["eid"] for e in u])
    while len(w_rows) < n_watchlist:                   # listed parties never seen in claims
        i = len(w_rows)
        e = _person_entity(fake, rng, f"{prefix}WO{i}", rng.random() < 0.5) if rng.random() < 0.85 else \
            _business_entity(fake, rng, f"{prefix}WO{i}")
        r = _row_from([e], f"{prefix}W{i:06d}", W_KEEP, rng)
        r["category"] = ""
        w_rows.append(r); w_ent.append([e["eid"]])
    W = pd.DataFrame(w_rows, columns=SCHEMA)
    X = pd.DataFrame(x_rows, columns=SCHEMA)
    W, _ = apply_noise(W, noise, fake, rng, scale=w_noise_scale, id_prefix="w")
    X, xlog = apply_noise(X, noise, fake, rng, scale=x_noise_scale, id_prefix="x")
    W["record_id"] = W["record_id"].str.replace("w:", "", regex=False)
    X["record_id"] = X["record_id"].str.replace("x:", "", regex=False)
    # claims and notes: shuffle the rows into claims of 1-5 rows, 1-3 notes each
    order = rng.permutation(len(X))
    ci, pos = 0, 0
    claim = np.empty(len(X), dtype=object); note = np.empty(len(X), dtype=object)
    while pos < len(order):
        k = int(rng.integers(1, 6)); idx = order[pos:pos + k]
        nn = int(rng.integers(1, 4))
        for j, t in enumerate(idx):
            claim[t] = f"{prefix}C{ci:06d}"; note[t] = f"{prefix}C{ci:06d}-N{j % nn}"
        ci += 1; pos += k
    X["claim_id"], X["note_id"] = claim, note
    # truth
    kind = {e["eid"]: e["kind"] for u in units for e in u}
    wi = defaultdict(list)
    for rid, ents in zip(W["record_id"], w_ent):
        for e in ents:
            wi[e].append(rid)
    truth = []
    for rid, ents in zip(X["record_id"], x_ent):
        for e in ents:
            part = "person" if kind.get(e) == "person" else "business"
            for wr in wi.get(e, []):
                truth.append((rid, part, wr))
    edges = edge_cases() if include_edges else []
    if edges:
        X = pd.concat([X, pd.DataFrame([r for c in edges for r in c["x"]], columns=SCHEMA)], ignore_index=True)
        W = pd.concat([W, pd.DataFrame([r for c in edges for r in c["w"]], columns=SCHEMA)], ignore_index=True)
        for c in edges:
            for ex in c["expect"]:
                if ex.get("w") and ex.get("true", ex.get("rank") == 1):
                    truth.append((ex["x"], ex["part"], ex["w"]))
    truth = pd.DataFrame(truth, columns=["x_record_id", "part", "w_record_id"]).drop_duplicates()
    X = X.fillna("").astype(str)
    W = W.fillna("").astype(str)
    return X, W, truth, edges, xlog


def make_scale_set(cfg, maps, ref):
    """The benchmark set: cfg.scale_watchlist watchlist rows and about cfg.scale_extracted
    extracted rows (not committed; written to data/)."""
    units = int(cfg.scale_extracted / 1.25)
    X, W, truth, _, _ = make_dataset(int(units * 0.83), int(units * 0.17), cfg.scale_watchlist, ref,
                                     maps["simulation_noise"], cfg.seed + 7, w_share=0.3,
                                     include_edges=False, prefix="Z")
    return X, W, truth
