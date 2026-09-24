"""Step 2 - Profile: describe each raw source before any rule is applied."""
import pandas as pd

KEYS = {
    "orders": "order_id", "restaurants": "restaurant_id", "drivers": "driver_id",
    "dispatch": "order_id", "interventions": "intervention_id", "outcomes_reference": "order_id",
}


def profile_table(name, df):
    lines = [f"### {name}", f"{len(df)} rows x {df.shape[1]} columns"]
    key = KEYS.get(name)
    if key:
        lines.append(f"- duplicate `{key}`: {df[key].duplicated().sum()}")

    lines += ["", "| column | nulls | distinct | sample / range |", "|---|---|---|---|"]
    for col in df.columns:
        s = df[col]
        if col.endswith(("_at", "_eta", "timestamp")):
            t = pd.to_datetime(s, errors="coerce", format="mixed")
            info = f"{t.min()} → {t.max()}; unparseable {int((t.isna() & s.notna()).sum())}"
        elif pd.api.types.is_numeric_dtype(s):
            info = f"min {s.min()}, median {s.median()}, max {s.max()}"
        elif s.nunique() <= 12:
            info = ", ".join(f"{k!r}:{v}" for k, v in s.value_counts(dropna=False).items())
        else:
            info = f"e.g. {s.dropna().iloc[0]!r}"
        lines.append(f"| {col} | {s.isna().sum()} | {s.nunique()} | {info} |")
    return "\n".join(lines)


def build_profile(raw, run_id):
    parts = [f"# Raw data profile (run {run_id})",
             "Generated from the raw snapshot before validation. Nothing here is cleaned.", ""]
    parts += [profile_table(name, df) + "\n" for name, df in raw.items()]
    return "\n".join(parts)
