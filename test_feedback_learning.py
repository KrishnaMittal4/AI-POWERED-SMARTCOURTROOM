import os, tempfile
fd,path=tempfile.mkstemp(suffix='.db'); os.close(fd)
os.environ['FEEDBACK_DB_PATH']=path
os.environ['FEEDBACK_MIN_EVENTS']='3'
from feedback_store import FeedbackStore
from feedback_learning import profile_adjustment, bounded_delta
s=FeedbackStore(path)
for _ in range(4): s.add('What does Section 138 provide?','a',rating=1,query_type='statutory')
assert bounded_delta(4,0)>0
# module-level helper reads FEEDBACK_DB_PATH set before import
p=profile_adjustment('What does Section 138 provide?')
assert p['events']>=3 and p['dense_multiplier']>1.0 and p['bm25_multiplier']<1.0
print('feedback learning smoke test passed',p)
os.unlink(path)
