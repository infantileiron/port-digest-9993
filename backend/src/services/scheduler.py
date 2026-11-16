import json,logging
from pathlib import Path
from sqlalchemy import select
from src.models.entities import Subscription,Receipt,Audit,DistributionGate
from src.services.repository import arrival_rows
from src.services.digest import calculate
from src.services.reconcile import evaluate_subscription,basis_for_receipt,lock_days
from src.constants.enums import STATIONS
from src.utils.time import aware,next_due,yesterday

SENT='sent'

def register_due(s,now):
 """到点只为“执行时刻的最新昨日”登记一张待发单；不补历史天。"""
 created=[]
 subscriptions=s.scalars(select(Subscription).where(Subscription.enabled.is_(True),Subscription.next_run_at<=now.isoformat()).with_for_update(skip_locked=True)).all()
 day=yesterday(now)
 for sub in subscriptions:
  if aware(sub.next_run_at)>now:continue
  existing=s.query(Receipt).filter_by(subscription_id=sub.id,report_day=day).first()
  gate=s.query(DistributionGate).filter_by(subscription_id=sub.id,report_day=day).first()
  if not existing and not gate:
   gate=DistributionGate(subscription_id=sub.id,report_day=day,state='waiting',reason='到点等待清单核对',blocking=[],attempts=0,first_blocked_at=now.isoformat(),updated_at=now.isoformat())
   s.add(gate);s.flush();created.append(gate.id)
   s.add(Audit(actor='scheduler',action=('到点登记晨报 '+str(sub.id)+' / '+day)[:200],created=now.isoformat()))
  sub.last_run_at=now.isoformat();sub.next_run_at=next_due(sub.daily_at,now).isoformat()
 return created

def _snapshot(evaluation):
 return {'state':'blocked' if evaluation['state']=='blocked' else 'waiting','reason':evaluation['reason'],'blocking':evaluation['blocking']}

def attempt_gate(s,gate_id,now):
 """在站日锁内重新核对后才入箱；旧核对、并发改账和换单都不能被当成齐备。"""
 gate=s.get(DistributionGate,gate_id)
 if not gate:return None
 # 先锁订阅行再按港站取日锁：换单/改站与分发串行，且不会因读到旧港站而锁错日锁。
 sub=s.query(Subscription).filter_by(id=gate.subscription_id).populate_existing().with_for_update().first()
 if not sub:return None
 day=gate.report_day
 if not sub.enabled:
  if gate.state!='paused':
   gate.state='paused';gate.reason='订阅已暂停';gate.updated_at=now.isoformat()
  return None
 if gate.state=='sent' and gate.receipt_id and s.query(Receipt).filter_by(id=gate.receipt_id).first():return None
 stations=list(STATIONS) if sub.station=='全部' else [sub.station]
 lock_days(s,stations,day)
 # 拿到日锁后按固定顺序重读 gate 与回执，消除与并发重试的窗口。
 gate=s.query(DistributionGate).filter_by(id=gate_id).populate_existing().with_for_update().first()
 if not gate:return None
 existing=s.query(Receipt).filter_by(subscription_id=sub.id,report_day=day).first()
 if existing:
  gate.state=SENT;gate.receipt_id=existing.id;gate.reason='已入箱';gate.blocking=[];gate.last_checked_at=now.isoformat();gate.updated_at=now.isoformat()
  return None
 evaluation=evaluate_subscription(s,sub,day)
 if evaluation['ready']:
  basis=basis_for_receipt(evaluation['stations'],now.isoformat())
  payload=calculate(arrival_rows(s),day,sub.station,basis)
  receipt=Receipt(subscription_id=sub.id,report_day=day,recipient=sub.recipient,created_at=now.isoformat(),state='delivered',payload=payload)
  s.add(receipt);s.flush()
  gate.state=SENT;gate.receipt_id=receipt.id;gate.reason='已入箱';gate.blocking=[];gate.attempts=(gate.attempts or 0)+1;gate.last_checked_at=now.isoformat();gate.updated_at=now.isoformat()
  s.add(Audit(actor='scheduler',action=('到点分发晨报 '+str(sub.id)+' / '+day+' 回执 '+str(receipt.id))[:200],created=now.isoformat()))
  return receipt
 snap=_snapshot(evaluation)
 changed=gate.state!=snap['state'] or gate.reason!=snap['reason'] or (gate.blocking or [])!=snap['blocking']
 if changed:
  # 同一阻塞原因只记一次重试并把状态落库，避免每秒写一次。
  gate.state=snap['state'];gate.reason=snap['reason'];gate.blocking=snap['blocking'];gate.last_checked_at=now.isoformat();gate.updated_at=now.isoformat()
  gate.attempts=(gate.attempts or 0)+1
  if not gate.first_blocked_at:gate.first_blocked_at=now.isoformat()
  s.add(Audit(actor='scheduler',action=('晨报受阻 '+str(sub.id)+' / '+day+'：'+snap['reason'])[:200],created=now.isoformat()))
 return None

def run_due(s,now):
 sent=[]
 try:
  register_due(s,now);s.commit()
 except Exception:
  s.rollback();logging.exception('due registration failed')
 gates=(s.query(DistributionGate).filter(DistributionGate.state!=SENT).order_by(DistributionGate.report_day,DistributionGate.id).all())
 for gate_id in [g.id for g in gates]:
  try:
   receipt=attempt_gate(s,gate_id,now)
   s.commit()
   if receipt is not None:sent.append(receipt.id)
  except Exception:
   s.rollback();logging.exception('delivery attempt failed for gate %s',gate_id)
 for i in sent:
  try:
   receipt=s.get(Receipt,i)
   Path('/artifacts/'+str(i)+'.json').write_text(json.dumps(receipt.payload,ensure_ascii=False,indent=2))
  except Exception:logging.exception('DB inbox delivered; optional artifact write failed')
 return sent
