from fastapi import APIRouter,Depends,HTTPException
from src.config.database import db
from src.models.entities import User,Subscription,Receipt,Audit
from src.schemas.business import Login,ArrivalInput,SubscriptionInput,PreviewInput,ReviewInput
from src.middlewares.auth import current,editor,admin
from src.utils.security import verify,token
from src.utils.time import now_utc,yesterday,SH
from src.services.business import audit,dump
from src.services.repository import arrival_rows,save_arrival,save_subscription,get_receipt
from src.services.digest import calculate
from src.controllers.business import export_receipt
router=APIRouter()
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
 r=save_arrival(s,data,i);audit(s,u,'修订班次 '+r.code);return dump(r)
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
