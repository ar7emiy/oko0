# %% [markdown]
# # 09 - Layer 4: Per-Claim Agentic Retrieval
#
# Hard claim filter -> scoped vector entry -> 1-2 hop graph expansion -> grounded
# synthesis with span citations. Includes the scope-isolation proof: the agent is
# structurally incapable of reading another claim's data.
#
# Requires notebook 08 to have run. `ClaimScopedAgent` raises
# `AgentStoreUnavailable` if either store is missing rather than answering from
# whatever happens to be loaded.

# %%
# --- bootstrap: make the src package importable from any working dir ---
import sys
from pathlib import Path

p = Path.cwd().resolve()
while not (p / "config" / "00_config.py").exists() and p != p.parent:
    p = p.parent
if str(p) not in sys.path:
    sys.path.insert(0, str(p))
print("project root:", p)

# %%
from src.agent import ClaimScopedAgent, test_scope_isolation
from src.repository import Repository

repo = Repository()
agent = ClaimScopedAgent(repo)
res = agent.answer("CLM0005",
                   "who represents the claimant and which providers treated them?")
print("SCOPE:", res["scope"])
print()
print("parties:", [(e["name"], e["class"]) for e in res["entities"]][:8])
print("triples retrieved:", len(res["triples"]))

# %%
print("ANSWER:")
print(res["answer"])
print()
print("citations:", res["citations"][:5])

# %% [markdown]
# ## Every retrieval step, shown

# %%
chunks = agent.retrieve_chunks("CLM0005", "attorney representation and treatment")
print("step 2 - scoped vector entry:")
for c in chunks:
    print(f"   {c['chunk_id']}  claim={c['claim_id']}  score={c['score']}")

# %%
eids = agent.entities_in_chunks("CLM0005", chunks)
print("step 3 - entities in those chunks:", len(eids))
for t in agent.expand("CLM0005", eids)[:8]:
    print(f"   {t['subject'][:24]:26s} --{t['predicate']:20s}--> {t['object'][:22]}")

# %% [markdown]
# ## Scope isolation proof
#
# Not a policy check — a structural one. The claim filter is applied inside the
# index before nearest-neighbour selection, so there is no code path that
# returns another claim's chunk and then filters it out.

# %%
iso = test_scope_isolation(agent, "CLM0005", "CLM0006")
for k, v in iso.items():
    print(f"  {k:34s} {v}")
assert iso["isolation_holds"], "SCOPE ISOLATION FAILED"
print()
print("scope isolation holds.")

# %% [markdown]
# ## Escalated cross-claim view - separately authorised
#
# The fraud-network question is real and the data supports it, but it is a
# different authorisation than "answer a question about this claim".

# %%
ents = [e["entity_id"] for e in res["entities"]]
links = agent.cross_claim_network(ents, authorized=True)
print("cross-claim links for these entities:", len(links))
for link in links[:5]:
    print(f"   {link['subject'][:22]:24s} --{link['predicate']:24s}--> "
          f"{link['object'][:22]:24s}")
    print(f"      subject claims: {link['claims_of_subject'][:4]}"
          f"  object claims: {link['claims_of_object'][:4]}")

# %%
repo.close()
