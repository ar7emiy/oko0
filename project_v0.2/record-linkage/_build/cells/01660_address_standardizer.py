ADDRESS_COMPONENTS = ["number", "direction", "name", "type", "unit", "city", "state", "zip"]


def _street_line(number, direction, name, stype, unit):
    u = fold(unit)
    if u and not re.match(r"^(APT|APARTMENT|UNIT|STE|SUITE|RM|ROOM|FL|FLOOR|BLDG|LOT|SPC|SPACE|TRLR|DEPT|#)\b", u):
        u = "# " + u
    return " ".join(x for x in (fold(number), fold(direction), fold(name), fold(stype), u) if x)


def parse_usaddress(line):
    """One street line -> (number, direction, name, type, unit) with the usaddress tagger, or
    None when it cannot be parsed. PO boxes become ('<box>', '', 'PO BOX', '', '')."""
    import usaddress
    if not line:
        return ("", "", "", "", "")
    try:
        tags, _ = usaddress.tag(line)
    except Exception:
        return None
    if "USPSBoxID" in tags:
        return (tags["USPSBoxID"], "", "PO BOX", "", "")
    number = " ".join(tags.get(k, "") for k in ("AddressNumberPrefix", "AddressNumber", "AddressNumberSuffix")).strip()
    name = " ".join(tags.get(k, "") for k in ("StreetNamePreModifier", "StreetNamePreType", "StreetName")).strip()
    predir = tags.get("StreetNamePreDirectional", "").replace(".", "")
    ws = name.split()
    if predir in ("N", "S") and len(ws) > 1 and ws[0] in ("E", "W"):      # 'N W 45TH' -> NW 45TH
        predir, name = predir + ws[0], " ".join(ws[1:])
    unit = " ".join(tags.get(k, "") for k in ("OccupancyIdentifier", "SubaddressIdentifier")).replace("#", "").strip()
    if not (number or name):
        return None
    return (number, predir, name, tags.get("StreetNamePostType", ""), unit)


class AddressStandardizer:
    """Street address -> components, by the chosen mode (see the section text). `post` is the
    HTTP call used by the smarty mode (injectable, so tests never reach the network)."""

    def __init__(self, mode="usaddress", cache_path=None, url="", batch=100, post=None, env=None):
        self.mode, self.cache_path, self.url, self.batch = mode, cache_path, url, batch
        self.post = post or self._http_post
        env = os.environ if env is None else env
        self.auth = (env.get("SMARTY_AUTH_ID", ""), env.get("SMARTY_AUTH_TOKEN", ""))
        self.report = defaultdict(int)
        self.report["mode"] = mode
        self._cache = None

    # ---- smarty ------------------------------------------------------------------------------
    def _load_cache(self):
        if self._cache is None:
            self._cache = {}
            if self.cache_path and Path(self.cache_path).exists():
                self._cache = json.loads(Path(self.cache_path).read_text(encoding="utf-8"))
        return self._cache

    def _save_cache(self):
        if self.cache_path and self._cache is not None:
            Path(self.cache_path).write_text(json.dumps(self._cache, indent=0, sort_keys=True), encoding="utf-8")

    def _http_post(self, url, params, payload):
        import urllib.request, urllib.parse
        q = urllib.parse.urlencode(params)
        req = urllib.request.Request(f"{url}?{q}", data=json.dumps(payload).encode("utf-8"),
                                     headers={"Content-Type": "application/json; charset=utf-8"})
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read().decode("utf-8"))

    @staticmethod
    def _smarty_key(street, city, state, zipc):
        return hashlib.sha1("\x1f".join((street, city, state, zipc)).encode("utf-8")).hexdigest()

    def _smarty(self, queries):
        """queries: {key: (street, city, state, zip)} -> {key: component tuple or None}."""
        cache = self._load_cache()
        out = {k: cache[k] for k in queries if k in cache}
        self.report["smarty_cache_hits"] += len(out)
        todo = [k for k in queries if k not in cache]
        if todo and not all(self.auth):
            self.report["smarty_no_credentials"] += len(todo)
            return out
        keys = sorted(todo)
        for i in range(0, len(keys), self.batch):
            chunk = keys[i:i + self.batch]
            payload = [{"input_id": k, "street": queries[k][0], "city": queries[k][1], "state": queries[k][2],
                        "zipcode": queries[k][3], "candidates": 1} for k in chunk]
            try:
                resp = self.post(self.url, {"auth-id": self.auth[0], "auth-token": self.auth[1]}, payload)
                self.report["smarty_calls"] += 1
            except Exception as ex:                               # a failed call is counted, not fatal
                self.report["smarty_errors"] += 1
                self.report["smarty_last_error"] = str(ex)[:200]
                continue
            got = {r.get("input_id"): r for r in resp or []}
            for k in chunk:
                r = got.get(k)
                if r is None:
                    cache[k] = None
                    continue
                c = r.get("components", {})
                cache[k] = [c.get("primary_number", ""), c.get("street_predirection", ""), c.get("street_name", ""),
                            c.get("street_suffix", ""), c.get("secondary_number", ""), c.get("city_name", ""),
                            c.get("state_abbreviation", ""), c.get("zipcode", "")]
            for k in chunk:
                if k in cache:
                    out[k] = cache[k]
        self._save_cache()
        return out

    # ---- all modes ---------------------------------------------------------------------------
    def standardize(self, df):
        """Input-schema rows -> DataFrame of ADDRESS_COMPONENTS (raw strings, same index)."""
        given = pd.DataFrame({"number": df["street_number"], "direction": df["street_direction"],
                              "name": df["street_name"], "type": df["street_type"], "unit": df["unit"],
                              "city": df["city"], "state": df["state"], "zip": df["zip"]}, index=df.index)
        self.report["rows"] += len(df)
        if self.mode == "given":
            return given
        lines = [_street_line(*t) for t in zip(df["street_number"], df["street_direction"], df["street_name"],
                                               df["street_type"], df["unit"])]
        out = given.copy()
        if self.mode == "smarty":
            q = {}
            keys = []
            for i, (line, c, s, z) in enumerate(zip(lines, df["city"], df["state"], df["zip"])):
                if not line:
                    keys.append("")
                    continue
                k = self._smarty_key(line, fold(c), fold(s), str(z).strip())
                q[k] = (line, fold(c), fold(s), str(z).strip())
                keys.append(k)
            res = self._smarty(q)
            done = np.zeros(len(df), dtype=bool)
            vals = {c: out[c].to_numpy(dtype=object).copy() for c in ADDRESS_COMPONENTS}
            for i, k in enumerate(keys):
                r = res.get(k) if k else None
                if r:
                    for c, v in zip(ADDRESS_COMPONENTS, r):
                        vals[c][i] = v or ""
                    done[i] = True
                elif k and k in res:
                    self.report["smarty_no_match"] += 1
            for c in ADDRESS_COMPONENTS:
                out[c] = vals[c]
            self.report["smarty_standardized"] += int(done.sum())
            rest = ~done
        else:
            rest = np.ones(len(df), dtype=bool)
        idx = np.flatnonzero(rest & (np.array(lines, dtype=object) != ""))
        if len(idx):
            if self.mode == "smarty":
                self.report["smarty_fallback_usaddress"] += len(idx)
            parsed = map_unique(pd.Series([lines[i] for i in idx]), parse_usaddress)
            vals = {c: out[c].to_numpy(dtype=object).copy() for c in ADDRESS_COMPONENTS[:5]}
            for j, t in zip(idx, parsed):
                if t is None:
                    self.report["usaddress_unparsed_kept_given"] += 1
                    continue
                for c, v in zip(ADDRESS_COMPONENTS[:5], t):
                    vals[c][j] = v
                self.report["usaddress_parsed"] += 1
            for c in ADDRESS_COMPONENTS[:5]:
                out[c] = vals[c]
        return out


def make_standardizer(cfg, post=None, env=None):
    return AddressStandardizer(cfg.address_standardizer, cfg.paths["smarty_cache"], cfg.smarty_url,
                               cfg.smarty_batch, post=post, env=env)
