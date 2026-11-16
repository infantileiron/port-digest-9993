import re
from datetime import date
from typing import Literal,Optional
from pydantic import BaseModel,Field,field_validator,model_validator,ValidationInfo
from src.utils.time import aware
class Login(BaseModel):email:str;password:str
class ArrivalInput(BaseModel):
 code:str=Field(min_length=1,max_length=60)
 station:Literal['北站','南站','东港']
 planned_at:str
 actual_at:Optional[str]=None
 note:str=Field(default='',max_length=1000)
 @field_validator('planned_at','actual_at')
 @classmethod
 def normalize(cls,v,info:ValidationInfo):
  if not v and info.field_name=='planned_at':raise ValueError('计划时间不能为空')
  return aware(v).isoformat() if v else None
 @model_validator(mode='after')
 def range(self):
  if self.actual_at and abs((aware(self.actual_at)-aware(self.planned_at)).total_seconds())>3*86400:raise ValueError('实际与计划时间相差超过3天，请核对')
  return self
class SubscriptionInput(BaseModel):
 name:str=Field(min_length=2,max_length=100)
 station:Literal['全部','北站','南站','东港']='全部'
 daily_at:str='08:30'
 recipient:str=Field(min_length=2,max_length=80)
 enabled:bool=True
 first_due_at:Optional[str]=None
 @field_validator('daily_at')
 @classmethod
 def clock(cls,v):
  if not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d',v):raise ValueError('每天时刻格式HH:MM')
  return v
 @field_validator('first_due_at')
 @classmethod
 def normalize(cls,v):return aware(v).isoformat() if v else None
class PreviewInput(BaseModel):
 report_day:date
 station:Literal['全部','北站','南站','东港']='全部'
class ReviewInput(BaseModel):note:str=Field(min_length=5,max_length=2000)
class ManifestInput(BaseModel):
 station:Literal['北站','南站','东港']
 report_day:date
 codes:list[str]=Field(min_length=1,max_length=500)
 note:str=Field(default='',max_length=1000)
 @field_validator('codes')
 @classmethod
 def tidy(cls,v):
  cleaned=[c.strip() for c in v if c and c.strip()]
  if not cleaned:raise ValueError('应到清单至少需要一条班次编号')
  if any(len(c)>60 for c in cleaned):raise ValueError('班次编号不能超过60字符')
  return cleaned
 @model_validator(mode='after')
 def unique(self):
  if len(set(self.codes))!=len(self.codes):raise ValueError('同一清单内班次编号不能重复')
  return self
