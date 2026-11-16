from datetime import datetime,timedelta,timezone
from zoneinfo import ZoneInfo
SH=ZoneInfo('Asia/Shanghai')
def aware(value):
 d=datetime.fromisoformat(value) if isinstance(value,str) else value
 if d.tzinfo is None:raise ValueError('时间必须包含时区偏移，例如+08:00')
 return d.astimezone(timezone.utc)
def now_utc():return datetime.now(timezone.utc)
def next_due(daily_at,now):
 h,m=map(int,daily_at.split(':'));local=now.astimezone(SH);candidate=local.replace(hour=h,minute=m,second=0,microsecond=0)
 if candidate<=local:candidate+=timedelta(days=1)
 return candidate.astimezone(timezone.utc)
def yesterday(now):return (now.astimezone(SH).date()-timedelta(days=1)).isoformat()
