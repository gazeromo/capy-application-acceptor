"""Astra-authored synthetic qualification vectors, not genuine Developer receipts.
The independent profile expectations below are fixed before the fixture source.
Actual verified product journeys are a separate post-contribution qualification.
"""
import copy
import json
from oracle import BASE,canon,sha,pack,unpack
from qualify import reseal

base=json.loads(unpack((BASE/'greeting.capya').read_bytes())['ACCEPTANCE-PROFILE.json'])
base.update(profile_id='csv-price-summary/v0',application_id='demo.csv_price_summary')
base['interaction_expectations']={'purpose':'Report product row count and average price.','operation_id':'csv.summarize','not_for':['calculating total spend or changing source data'],'request_fields':[],'resource_fields':[{'slot':'products','required':True,'min_items':1,'max_items':1}],'result_fact_paths':['row_count','average_price'],'artifact_filenames':[],'boundaries':[{'boundary_id':'csv.total','nearest_operation_ids':['csv.summarize']}]}
cases=[('normal',b'name,price\na,100\nb,200\nc,600\n',{'row_count':3,'average_price':300.0},None),('zero',b'name,price\na,0\nb,0\n',{'row_count':2,'average_price':0.0},None),('invalid',b'name,price\na,invalid\n',None,'PRODUCT_CSV_INVALID'),('empty',b'name,price\n',None,'PRODUCT_CSV_EMPTY')]
base['cases']=[];files={}
for cid,payload,result,failure in cases:
    member=f'fixtures/{cid}/products.csv';files[member]=payload
    base['cases'].append({'case_id':cid,'request':{},'resources':[{'slot':'products','filename':'products.csv','member':member,'sha256':sha(payload)}],'expect':{'status':'failed' if failure else 'ok','result':result,'artifacts':[],'failure_code':failure}})
(BASE/'csv-mean.capya').write_bytes(pack({'ACCEPTANCE-PROFILE.json':canon(base),**{n:files[n] for n in sorted(files)}}))
# Only after writing the independent profile, create the synthetic application.
interaction={'schema':'capy.application-interaction/dev-v0','application_id':'demo.csv_price_summary','title':'CSV Price Summary','purpose':'Report product row count and average price.','not_for':['calculating total spend or changing source data'],'operation':{'operation_id':'csv.summarize','title':'Summarize CSV','user_outcome':'Receive a row count and average price.','description':'Read one supplied CSV and summarize its price column.','request_fields':[],'resource_fields':[{'slot':'products','label':'Products CSV','description':'One CSV with a price column.','required':True,'minimum_count':1,'maximum_count':1,'input_kind':'file','examples':['products.csv'],'clarification_question':'Which products CSV should be summarized?'}],'examples':['Summarize this products CSV.'],'common_misunderstandings':['Average price is not total spend.'],'result':{'presentation':'facts','facts':[{'path':'row_count','label':'Row count'},{'path':'average_price','label':'Average price'}],'artifacts':[]}},'boundaries':[{'boundary_id':'csv.total','request_class':'calculating total spend','explanation':'This operation provides an average, not a spend total.','nearest_operation_ids':['csv.summarize']}]}
descriptor='''schema = "capy.script/dev-v0"
id = "demo.csv_price_summary"
name = "CSV Price Summary"
description = "Report product row count and average price."
entrypoint = "main.py"
side_effect = "read_only"
timeout_seconds = 5
memory_mb = 128
state_required = false
connections = []
[[resources]]
name = "products"
required = true
min_items = 1
max_items = 1
[input_schema]
type = "object"
additionalProperties = false
[result_schema]
type = "object"
required = ["row_count", "average_price"]
additionalProperties = false
[result_schema.properties.row_count]
type = "integer"
minimum = 0
[result_schema.properties.average_price]
type = "number"
minimum = 0
'''
source='''import csv
import io
from decimal import Decimal, InvalidOperation
from capy_script import Context
ctx=Context()
if ctx.request:ctx.fail("REQUEST_INVALID")
try:
    rows=list(csv.DictReader(io.StringIO(ctx.resource("products").one().read_text())))
    prices=[Decimal(row["price"]) for row in rows]
    if any(not x.is_finite() or x<0 for x in prices):raise ValueError()
except (KeyError,ValueError,InvalidOperation):ctx.fail("PRODUCT_CSV_INVALID")
if not prices:ctx.fail("PRODUCT_CSV_EMPTY")
ctx.complete({"row_count":len(prices),"average_price":float(sum(prices)/len(prices))})
'''
golden=(BASE/'fixed-v1.capyrc').read_bytes()
correct=reseal(golden,change_app=lambda app:app.update({'capability.toml':descriptor.encode(),'interaction.json':canon(interaction),'main.py':source.encode()}))
(BASE/'csv-correct.capyrc').write_bytes(correct)
wrong=reseal(correct,change_app=lambda app:app.update({'main.py':app['main.py'].replace(b'float(sum(prices)/len(prices))',b'float(sum(prices))')}))
(BASE/'csv-wrong-value.capyrc').write_bytes(wrong)
i=copy.deepcopy(interaction);i['purpose']='Report product row count and total price.';i['operation']['result']['facts'][1]['path']='total_price'
total=reseal(correct,change_app=lambda app:app.update({'capability.toml':descriptor.replace('average_price','total_price').encode(),'interaction.json':canon(i),'main.py':source.replace('average_price','total_price').replace('sum(prices)/len(prices)','sum(prices)').encode()}))
(BASE/'csv-total.capyrc').write_bytes(total)
