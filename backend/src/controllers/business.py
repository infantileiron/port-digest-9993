import json
from fastapi import Response
from src.services.repository import get_receipt
from src.services.business import dump
def export_receipt(s,i):
 r=get_receipt(s,i)
 return Response(json.dumps(dump(r),ensure_ascii=False,indent=2),media_type='application/json',headers={'Content-Disposition':f'attachment; filename="port-digest-{r.report_day}-{i}.json"'})
