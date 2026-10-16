"""Fast local smoke checks for LEXAI. Does not call Groq/Gemini."""
import sys

def check(name, fn):
    try:
        fn(); print(f"PASS {name}"); return True
    except Exception as e:
        print(f"FAIL {name}: {e}"); return False

def main():
    ok=[]
    from legal_judgment_intelligence import classify_legal_role
    from product_readiness import evidence_strength
    ok.append(check("court-role classifier", lambda: (_ for _ in ()).throw(AssertionError()) if classify_legal_role("We therefore hold that the appeal is allowed.")["role"] not in {"RATIO","FINAL_ORDER","COURT_REASONING"} else None))
    ok.append(check("party-role classifier", lambda: (_ for _ in ()).throw(AssertionError()) if classify_legal_role("Learned counsel for the appellant submitted that the order is invalid.")["role"] != "PETITIONER_ARGUMENT" else None))
    sample={"existence":{"exists_in_corpus":True},"passage_support":{"verdict":"yes","agreement":True,"independent_provider":True},"attribution":{"status":"supported","checked":True,"passage_roles":["RATIO"]}}
    ok.append(check("evidence strength", lambda: (_ for _ in ()).throw(AssertionError()) if evidence_strength(sample)["level"] != "high" else None))
    try:
        import main
        ok.append(check("ASGI app import", lambda: getattr(main,"app")))
    except Exception as e:
        print(f"WARN ASGI app import unavailable in this environment: {e}")
    return 0 if all(ok) else 1
if __name__ == '__main__': sys.exit(main())
