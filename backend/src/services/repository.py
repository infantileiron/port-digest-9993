from sqlalchemy.exc import IntegrityError
from fastapi import HTTPException
from src.models.entities import Arrival,Subscription,Receipt
from src.services.business import dump
from src.services.reconcile import invalidate_station,lock_day,planned_day
from src.constants.enums import STATIONS
from src.utils.time import now_utc,next_due

def arrival_rows(s):return [dump(r) for r in s.query(Arrival).order_by(Arrival.planned_at,Arrival.id).all()]

def _keys(a,b):
 """同一站日的日锁按（港站序、业务日）固定顺序获取，避免并发改账与分发互锁。"""
 return sorted({k for k in (a,b) if k},key=lambda k:(STATIONS.index(k[0]),k[1]))

def save_arrival(s,data,i=None):
 r=s.get(Arrival,i) if i else Arrival()
 if not r:raise HTTPException(404,'到发记录不存在')
 old=None if i is None else (r.station,planned_day(r.planned_at))
 new=(data.station,planned_day(data.planned_at))
 for key in _keys(old,new):lock_day(s,*key)
 values=data.model_dump()
 for k,v in values.items():setattr(r,k,v)
 r.revision=(r.revision or 0)+1
 s.add(r)
 try:
  s.flush()
 except IntegrityError:
  s.rollback();raise HTTPException(409,'班次编号重复')
 when=now_utc().isoformat()
 for key in _keys(old,new):
  invalidate_station(s,key[0],key[1],'台账在核对后有修订',when)
 try:s.commit()
 except IntegrityError:s.rollback();raise HTTPException(409,'班次编号重复')
 return r

def save_subscription(s,data,i=None):
 r=s.get(Subscription,i) if i else Subscription();new=i is None
 if not r:raise HTTPException(404,'订阅不存在')
 values=data.model_dump();first=values.pop('first_due_at')
 for k,v in values.items():setattr(r,k,v)
 # Explicit edit schedules the next future run; an initial override is for a first/catch-up delivery.
 r.next_run_at=first or next_due(r.daily_at,now_utc()).isoformat()
 s.add(r)
 try:s.commit()
 except IntegrityError:s.rollback();raise HTTPException(409,'订阅名称重复')
 return r

def get_receipt(s,i):
 r=s.get(Receipt,i)
 if not r:raise HTTPException(404,'回执不存在')
 return r
