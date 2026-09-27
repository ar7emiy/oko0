## 2a · Address standardization (US)

One setting, `address_standardizer`, chooses how the street address becomes components. All
three produce the same fields (number, pre-direction, street name, street type, unit, city,
state, ZIP), which the core's normalizers then abbreviate the USPS way:

| Setting | What it does |
|---|---|
| `given` | the input is already standardized (by SmartyStreets upstream, say): the components are used as given |
| `usaddress` (default, offline) | the street columns are rejoined into one line and parsed with the `usaddress` tagger, so a whole line typed into `street_name`, a unit inside the name or a missing type are repaired; a line the tagger cannot parse keeps its given components (counted) |
| `smarty` | the SmartyStreets US Street API: credentials from `SMARTY_AUTH_ID` / `SMARTY_AUTH_TOKEN`, batches of 100, every answer cached in `data/smarty_cache.json`. Without credentials, or for an address Smarty cannot match, the row falls back to `usaddress`, and the manifest says how many. The self-tests never call the service (a fake stands in) |

City, state and ZIP come from their own columns in every mode except `smarty`, which returns
its own.

**Where Splink would do better.** Nowhere: Splink leaves address cleaning to the user and
has no address parser; its comparison library compares address strings as given. The
parsing here is ours.
