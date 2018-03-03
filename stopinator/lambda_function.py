#AWS LAmbda function to stop/start EC2 instance
#Note: this will disable Auto Scaling group
import pytz
import boto3
import datetime
import time
import calendar


#TIME_FORMAT = '%Y-%m-%d %H:%M:%S'
CONST_ASG_RESUME_KEY="stopinator:resume:time"

#initalising
default_timezone = "Australia/NSW"
asgclient = boto3.client('autoscaling',region_name="ap-southeast-2")

d={"1":"name"}
def current_time(event):
  current=[0,0,""]
  tz = default_timezone

  if not event:
     tz = default_timezone
     print "Loading default timezone`"
  else:
     tz = event.get("timezone")
     if not tz:
        tz = default_timezone
        print "Loading default timezone "+default_timezone

  print tz
  timezone = pytz.timezone (tz)

  datetime_with_tz = datetime.datetime.now(timezone)
  current[0] = datetime_with_tz.hour
  current[1] = datetime_with_tz.minute
  current[2] = datetime_with_tz.strftime("%Y-%m-%dT%H:%M")
  return current



## get tag value by key
def get_tag_val(arg,tags):
    val = ""
    for x in tags:
       if x['Key'] == arg:
          val = x['Value']
    return val
 
## get start/end time defined in ec2 tags
## time:start /time:stop 
def start_end_time(arg,tags):
   v =""
   
   
   r=[111,211]
   
   for x in tags:
	if x['Key'] == arg:
	   v = x['Value']
           #print v
           timepart= v.split(':')
           r[0]= int(timepart[0])
           r[1]=int(timepart[1])

   return r


## stop instance
def suspend_asg(name):
    print "suspending asg:"+name    
    response = asgclient.suspend_processes(
    	AutoScalingGroupName=name
    )
    print response   
def resume_asg(name):
    print "Resuming asg :"+name
    response = asgclient.resume_processes(
    	AutoScalingGroupName=name,
    )
    print response
    print "remove schedule"  
    response = asgclient.delete_tags(
    	Tags=[{
            "ResourceId": name,
            "Key": CONST_ASG_RESUME_KEY,
        }]
    )
    print respone
    


def stop_instance(ec2,instance,event):
    iid = instance.get("InstanceId")
    current = current_time(event)
    #print('stopiing instance ',iid)
    current = current_time(event)
    ec2.create_tags(Resources=[iid], Tags=[{"Key":"stopinator:stop:time","Value":current[2]}])
    if iid in d:
        print "has associated asg.need to suspend it first"
        asg = d[iid]
        suspend_asg(asg)
        
    
    print ec2.stop_instances(InstanceIds=[iid])



##start instanc
def start_instance(ec2,instance,event):
    iid = instance.get("InstanceId")
    print ec2.start_instances(InstanceIds=[iid])
    ctime = current_time(event)
    cdate = ctime[2].split("T")
        

    current = start_end_time("time:start",instance.get("Tags"))
    hh=""
    if current[0] < 10:
       hh="0"+`current[0]`
    else:
       hh=""+`current[0]`  
    cdatetime = cdate[0]+"T"+hh+":"

    if current[1] < 10:
       cdatetime = cdatetime + "0"+`current[1]`
    else:
       cdatetime = cdatetime+`current[1]`
     
    ec2.create_tags(Resources=[iid], Tags=[{"Key":"stopinator:start:time","Value":cdatetime}])
    #schedule asg resume if instance is part of ASG (need to make sure it resume after all the instance are on)
    if iid in d:
       name = d[iid];
       ctime[1] = ctime[1]+10 
       lt = ""+`ctime[0]`+":"+`ctime[1]`
       asgclient.create_tags(Resources=[name], Tags=[{"Key":"stopinator:start:time","Value":lt}])

## load auto scaling load to a map
def scan_asg(event):


    print "loading autoscale groups"
    client = boto3.client('autoscaling',region_name='ap-southeast-2')
    response = client.describe_auto_scaling_groups()

    #print response
    #nextToken = response['NextToken']
    asgs = response['AutoScalingGroups']
    for asg in asgs:
        name = asg['AutoScalingGroupName']
        tags = asg["Tags"]
        ## starting suspended asgs based on tiem 
        v = start_end_time(CONST_ASG_RESUME_KEY,tags)
        if not v:
           print "no asg schedule(nothing to resume)"
        else:
           c = current_time(event)
           if c[0] > v[0]:
              resume_asg(name)
           if c[0]==v[0] and c[1] >= v[1]:
              resume_asg(name)
        # end asg stuff

        #print asg['AutoScalingGroupName'],'\n'
        for instance in asg['Instances']:
            iid= instance['InstanceId']
            d[iid] = name




def can_start(current, time_b,time_e,tags):
  ch = current[0]
  cm = current[1]

  #dealing with manual stopping (make sure schedular not going to start it again)
  current_dtm = current[2]
  same_day = False
  last_start = get_tag_val("stopinator:start:time",tags)

  print "Last:start:time",last_start

  if not last_start:
     same_day = False
  else: 
     date = current_dtm.split("T")
     ls_date = last_start.split("T")
     print "last start date:"+ls_date[0]+", current date:"+date[0]
     if date[0] == ls_date[0]:
        #mark schedular is already started it.. cancel the starting operation if it see it should   
        same_day = True 
        
  can = False
  
  if ch > time_b[0] and ch < time_e[0]:
     print "cond1-start"
     can = True
     
  if time_b[0] == ch and time_e[0] == ch and cm >= time_b[1]  and time_e[1] < cm:
     #print "cond2-start"
     can = True
     
  if time_b[0] == ch and cm >= time_b[1]:
     #print "cond3-start"
     can = True

  #print "can before",can 

  #if can and same_day:
  #   print "stopinator already startd this instance:not going to start again(do manually)"

  can = can and not same_day
  #print "can",can
  return can  



     
def can_stop(ch,cm,time_b,time_e):

  can = False

  if ch > time_e[0]:
     can = True
  if time_e[0] == ch and cm >= time_e[1]:
     print "cond-2-stop"
     can = True

  return can   


def instance_filter(event):
    df =["linear*","linear-dev*"]
    pattern = df
    filters = [{'Name':'tag:stopinator','Values':['true']}]
    if not event:
       print "loading default pattern ",f
    else:
        pattern = event.get("target")
        if not pattern:
           pattern = df
    f={'Values':pattern,'Name':'tag:Name'}   
   
    filters.append(f)     
    return filters;
 
def lambda_handler(event, context):
    
    print("event content:",event)
     
    scan_asg(event)
    #curent time calc (diffrent time zone support)
    current = current_time(event)
    
    ch = current[0]
    cm = current[1]
    awstime = "Execute Time: "+`ch`+":"+`cm`+" hours."

    ec2 = boto3.client('ec2',region_name='ap-southeast-2')
    filters = instance_filter(event)
    print "Using filters",filters
    reservations=ec2.describe_instances(Filters=filters)
    print "found  "+`len(reservations['Reservations'])`+" Reservation matches"

    for r in reservations['Reservations']:
        #print(r,"\n\n")
        #print(r,"=======================================")
        for i in r['Instances']:
            iid=i['InstanceId']
            print('checking instance id',iid)
            date= i.get('LaunchTime')
            tags =i['Tags']
            print "analysing instance :"+`iid`+" - "+get_tag_val("Name",tags)

            ## start /end time extraction from tags
            time_e = start_end_time('time:stop',tags)
            time_b = start_end_time('time:start',tags)
            print awstime           
            print "time:stop  (HH:mm)"+`time_e[0]`+":"+`time_e[1]`
            print "time:start (HH:mm)"+`time_b[0]`+":"+`time_b[1]` 
            stated = i['State']
            stateId = stated.get('Code')
            print "current instance SateId:"+`stateId`
            executeStop = False
            #stop condition
            if stateId == 16:
               if can_stop(ch,cm,time_b,time_e):
                  print "STOPING INSTANCE",iid
                  stop_instance(ec2,i,event)
                  executeStop = True
            #start condition
            if not executeStop:
               if stateId == 80:
                  print "Instance stateId:"+`stateId` 
                  if can_start(current,time_b,time_e,tags):
                     print "STARTING INSTANCE:"+iid
                     start_instance(ec2,i,event)
                             
    return "OK"

