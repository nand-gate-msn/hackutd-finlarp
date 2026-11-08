import sys,json
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2] / 'server'))
from fastapi.testclient import TestClient
from app import main
from app.config import settings
from tests.test_nodes import CAR,GOOD_SUMMARY,FakeNemotron,deps_for,json_reply,proposals_reply,tool_reply
settings.monte_carlo_runs=1000
fake=FakeNemotron(planner=[tool_reply(CAR)],explainer=[json_reply({'summary':GOOD_SUMMARY})],action=[proposals_reply(('acct_A','acct_B',3,'Build a steadier savings cushion.'))],critic=[json_reply({'ok':True,'issues':[]})])
main.app.dependency_overrides[main.get_deps]=lambda:deps_for(fake)
c=TestClient(main.app)
r=c.post('/api/advise',json={'request':'Can I afford a car?'})
open(sys.argv[1] if len(sys.argv)>1 else '/private/tmp/finlarp-qa/advise.sse','w').write(r.text)
print(r.status_code, 'result' in r.text)
