from fastapi import APIRouter,Depends,HTTPException
from src.config.database import db
from src.models.entities import User,Subscription,Receipt,Audit,Manifest,Reconciliation,DistributionGate
from src.schemas.business import Login,ArrivalInput,SubscriptionInput,PreviewInput,ReviewInput,ManifestInput
from src.middlewares.auth import current,editor,admin
from src.utils.security import verify,token
from src.utils.time import now_utc,yesterday,SH
from src.services.business import audit,dump
from src.services.repository import arrival_rows,save_arrival,save_subscription,get_receipt
from src.services.digest import calculate
from src.services.reconcile import issue_manifest,reconcile_manifest,evaluate_station,evaluate_subscription
from src.constants.enums import STATIONS
from src.services.scheduler import attempt_gate
from src.controllers.business import export_receipt
router=APIRouter()
def _manifest_dump(m):
 d=dump(m);d['items']=d.get('items') or [];return d
@router.post('/auth/login')
def login(data:Login,s=Depends(db)):
 u=s.query(User).filter_by(email=data.email).first()
 if not u or not verify(data.password,u.password):raise HTTPException(401,'账号或密码错误')
 return {'token':token(u),'user':dump(u)}
@router.get('/me')
def me(u=Depends(current)):return dump(u)
@router.get('/context')
def context(u=Depends(current)):
 now=now_utc();return {'now':now.isoformat(),'yesterday':yesterday(now),'timezone':'Asia/Shanghai'}
@router.get('/arrivals')
def arrivals(u=Depends(current),s=Depends(db)):return arrival_rows(s)
@router.post('/arrivals')
def create_arrival(data:ArrivalInput,u=Depends(editor),s=Depends(db)):
 r=save_arrival(s,data);audit(s,u,'录入班次 '+r.code);return dump(r)
@router.put('/arrivals/{i}')
def edit_arrival(i:int,data:ArrivalInput,u=Depends(editor),s=Depends(db)):
 r=save_arrival(s,data,i);audit(s,u,'修订班次 '+r.code+'（核对依据已失效）');return dump(r)
@router.post('/preview')
def preview(data:PreviewInput,u=Depends(editor),s=Depends(db)):
 result=calculate(arrival_rows(s),data.report_day.isoformat(),data.station);audit(s,u,'晨报试算 '+data.report_day.isoformat());return result
@router.get('/subscriptions')
def subscriptions(u=Depends(current),s=Depends(db)):return [dump(r) for r in s.query(Subscription).order_by(Subscription.id).all()]
@router.post('/subscriptions')
def create_subscription(data:SubscriptionInput,u=Depends(admin),s=Depends(db)):
 r=save_subscription(s,data);audit(s,u,'创建订阅 '+r.name);return dump(r)
@router.put('/subscriptions/{i}')
def edit_subscription(i:int,data:SubscriptionInput,u=Depends(admin),s=Depends(db)):
 r=save_subscription(s,data,i);audit(s,u,'修订订阅 '+r.name);return dump(r)
@router.get('/receipts')
def receipts(u=Depends(current),s=Depends(db)):return [dump(r) for r in s.query(Receipt).order_by(Receipt.id.desc()).all()]
@router.get('/receipts/{i}/export')
def export(i:int,u=Depends(current),s=Depends(db)):return export_receipt(s,i)
@router.post('/receipts/{i}/review')
def review(i:int,data:ReviewInput,u=Depends(admin),s=Depends(db)):
 r=get_receipt(s,i)
 if r.state=='reviewed':raise HTTPException(409,'回执已复核，不覆盖原复核意见')
 r.state='reviewed';r.review_note=data.note;s.commit();audit(s,u,'复核晨报回执 '+str(i));return dump(r)
@router.get('/audits')
def audits(u=Depends(admin),s=Depends(db)):return [dump(r) for r in s.query(Audit).order_by(Audit.id.desc()).limit(100)]

# ---- 应到清单与对账 ----
@router.get('/manifests')
def manifests(report_day:str|None=None,station:str|None=None,u=Depends(current),s=Depends(db)):
 q=s.query(Manifest)
 if report_day:q=q.filter_by(report_day=report_day)
 if station:q=q.filter_by(station=station)
 return [_manifest_dump(m) for m in q.order_by(Manifest.report_day.desc(),Manifest.station,Manifest.version.desc()).all()]
@router.post('/manifests')
def create_manifest(data:ManifestInput,u=Depends(editor),s=Depends(db)):
 m,changed=issue_manifest(s,data,u.email)
 audit(s,u,'出具应到清单 '+m.station+' / '+m.report_day+' v'+str(m.version)+('（换版）' if changed else '（内容相同，未换版）'))
 s.commit();return _manifest_dump(m)
@router.get('/manifests/{i}')
def manifest_detail(i:int,u=Depends(current),s=Depends(db)):
 m=s.get(Manifest,i)
 if not m:raise HTTPException(404,'应到清单不存在')
 reconciliations=[dump(r) for r in s.query(Reconciliation).filter_by(manifest_id=m.id).order_by(Reconciliation.id.desc()).all()]
 d=_manifest_dump(m);d['reconciliations']=reconciliations;return d
@router.post('/manifests/{i}/reconcile')
def reconcile(i:int,u=Depends(editor),s=Depends(db)):
 m,rec,result=reconcile_manifest(s,i,u.email)
 audit(s,u,'核对应到清单 '+m.station+' / '+m.report_day+' v'+str(m.version)+'：'+('齐备' if result['balanced'] else '差异 '+str(len(result['blocking']))+' 条'))
 s.commit();return {'manifest':_manifest_dump(m),'reconciliation':dump(rec)}
@router.get('/reconciliations')
def reconciliations(report_day:str|None=None,u=Depends(current),s=Depends(db)):
 q=s.query(Reconciliation)
 if report_day:q=q.filter_by(report_day=report_day)
 return [dump(r) for r in q.order_by(Reconciliation.id.desc()).limit(200).all()]
@router.get('/gates')
def gates(report_day:str|None=None,u=Depends(current),s=Depends(db)):
 q=s.query(DistributionGate)
 if report_day:q=q.filter_by(report_day=report_day)
 return [dump(g) for g in q.order_by(DistributionGate.report_day.desc(),DistributionGate.id).all()]
@router.get('/station-status')
def station_status(report_day:str|None=None,u=Depends(current),s=Depends(db)):
 day=report_day or yesterday(now_utc())
 return [evaluate_station(s,station,day) for station in STATIONS]
@router.get('/gateboard')
def gateboard(report_day:str|None=None,u=Depends(current),s=Depends(db)):
 """按订阅汇总该业务日的放行状态；多站订单一站未齐整份等待，不部分出报。"""
 day=report_day or yesterday(now_utc())
 subs=s.query(Subscription).order_by(Subscription.id).all()
 board=[evaluate_subscription(s,sub,day) for sub in subs]
 return {'report_day':day,'subscriptions':board}
@router.post('/gates/{i}/retry')
def retry_gate(i:int,u=Depends(admin),s=Depends(db)):
 g=s.get(DistributionGate,i)
 if not g:raise HTTPException(404,'分发放行记录不存在')
 receipt=attempt_gate(s,g.id,now_utc())
 s.commit()
 audit(s,u,'手动重试晨报 '+str(g.subscription_id)+' / '+g.report_day+('：已入箱' if receipt else '：仍受阻'))
 gate=s.get(DistributionGate,i)
 return {'gate':dump(gate),'receipt_id':gate.receipt_id if gate else None}
