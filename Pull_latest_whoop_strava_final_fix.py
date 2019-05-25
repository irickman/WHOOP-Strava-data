import requests
import pandas as pd
from selenium import webdriver
from selenium.webdriver.common.keys import Keys
from bs4 import BeautifulSoup as BS
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import StaleElementReferenceException
from selenium.webdriver.firefox.options import Options as fOptions
from selenium.webdriver.chrome.options import Options as cOptions
import configparser
import time
import datetime
import swagger_client
from swagger_client.rest import ApiException
import pygsheets
import math
import numpy as np
import os


#authorization
gc = pygsheets.authorize(credentials_directory='/home/irarickman')
file = 'Activity data'
sh = gc.open(file)

wks_1 = sh[0]
strav=wks_1.get_as_df(empty_value=np.nan)
strav.dropna(how='all',inplace=True)

wks_2=sh[1]
whoo=wks_2.get_as_df(empty_value=np.nan)
whoo.dropna(how='all',inplace=True)
whoo.dropna(axis=1,how='all',inplace=True)

wks_3=sh[2]

def get_strava(last_date=False):
    ## Getting log in info
    config = configparser.ConfigParser()
    config.read("/home/irarickman/strava.ini")
    params={'client_id':config['strava']['client_id'],
            'client_secret':config['strava']['client_secret'],
            'code':config['strava']['code']}
    auth_url=config['strava']['auth_url']
    ref_url=config['strava']['ref_url']
    athlete_id=config['strava']['athlete_id']
    
    if not last_date:
        ## Getting the most recent date
        last_date=datetime.datetime.strptime(strav.start_date.max().split(' ')[0],"%Y-%m-%d")
    else:
        last_date=datetime.datetime.strptime(last_date,"%Y-%m-%d")
    timestamp=last_date.timestamp()
    delta=datetime.datetime.now() - last_date
    date_diff=delta.days+5

    r_auth = requests.post(auth_url, data=params)
    response=r_auth.json()

    configuration = swagger_client.Configuration()
    configuration.access_token = response['access_token']

    # create an instance of the API class
    api_instance = swagger_client.ActivitiesApi(swagger_client.ApiClient(configuration))
    if date_diff<200:
        try:
            # Get Authenticated Athlete
            api_response = api_instance.get_logged_in_athlete_activities(after=timestamp, per_page=date_diff)
        except ApiException as e:
            print("Exception when calling AthletesApi->get_logged_in_athlete: {}\n".format(e))
    else:
        num_rounds=math.ceil(date_diff/200)
        api_response=[]
        for n in range(num_rounds):
            if n==num_rounds:
                page_num=date_diff-(200*(n-1))
            else:
                page_num=200
            try:
                # Get Authenticated Athlete
                activities = api_instance.get_logged_in_athlete_activities(after=timestamp, page=n+1,per_page=page_num)
            except ApiException as e:
                print("Exception when calling AthletesApi->get_logged_in_athlete: {}\n".format(e))
            api_response=api_response+activities
                
    example=list(api_response[len(api_response)-1].to_dict().keys())
    example=[x for x in example if x not in ['map','athlete','start_latlng','end_latlng']]
    dicts={}
    for n in range(len(api_response)):
        d=api_response[n].to_dict()
        new_dict={variable:d[variable] for variable in example}
        dicts[n]=new_dict

    index=list(dicts.keys())
    strava=pd.DataFrame([dicts[key] for key in index],index=index)
    mult_mile=0.000621371
    strava['miles']=strava.distance*mult_mile
    strava['race']=strava.workout_type.apply(lambda x: 1 if x in [1.0,11.0] else 0 )
    strava['date_string']=strava.start_date_local.astype(str).apply(lambda x: x[:10])
    strava['moving_minutes']=strava.moving_time/60
    strava['elapsed_minutes']=strava.elapsed_time/60
    strava['rest']=strava.elapsed_minutes-strava.moving_minutes
    ## average speed is in meters/second - 2.237 to multiply to mph
    strava['avg_mph']=strava.average_speed*2.237
    strava['time_since_last_act']=(pd.to_datetime(strava.start_date)-pd.to_datetime(strava.start_date.shift(-1))).astype('timedelta64[h]')
    strava.start_date=pd.to_datetime(strava.start_date_local)
    strava.sort_values('start_date',inplace=True)
    strava['order']=strava.groupby('date_string').start_date.rank()
    if len(strav)==0:
        wks_1.set_dataframe(strava,(1,1))
    else:
        all_acts=pd.concat([strava,strav])
        all_acts.drop_duplicates(['id'],keep='first',inplace=True)
        wks_1.set_dataframe(all_acts,(1,1))

def get_whoop(most_recent=False):
    
    config = configparser.ConfigParser()
    config.read("/home/irarickman/strava.ini") 
    w='https://app.whoop.com/login'
    
    options_list = cOptions()  
    #options_list.headless=True
    options_list.add_argument("--headless") 
    options_list.add_argument('--no-sandbox')
   # options_list.binary_location = '/opt/firefox/firefox-bin'
    options_list.binary_location = '/usr/bin/chromium'

    browser=webdriver.Chrome('chromedriver',options=options_list)
    #browser=webdriver.Firefox(executable_path='/opt/geckodriver-0.24.0',options=options_list)
    browser.get(w)
    
    username=browser.find_element_by_name('username')
    password=browser.find_element_by_name('password')
    username.send_keys(config['whoop']['username'])
    password.send_keys(config['whoop']['pass'])
    submit=browser.find_element_by_name('form')
    submit.click()
    
    def go_to_strain():
        work=0
        while work==0:
            try:
                strain_click=browser.find_elements_by_class_name('score')[0]
                strain_click.click()
                work=1
            except (StaleElementReferenceException,IndexError):
                work=0
        
    ## goal function is tos look for the activity - if it doesn't exist, then look for "no activity" 
## store the result, if the old activity strain is the same as the new

    def get_activity_strain(old_strain,old_date):
        work=0
        while work==0:
            try:
                buttons=browser.find_elements_by_tag_name('button')
                new_strain=[x.text for item in [x for x in [span.find_elements_by_tag_name('span') for span in [b for b in buttons if b.get_attribute("ng-click")=="click($event, activity.id)"]]] for x in item]
                if len(new_strain)==0:
                    new_strains=["null"]*6
                elif len(new_strain)<7:
                    new_strains=new_strain+['null']*(6-len(new_strain))
                else:
                    new_strains=new_strain
                if old_strain!=new_strains:
                    return new_strains
                    work=1
                elif old_date!=get_date(old_date):
                    return new_strains
                    work=1
            except StaleElementReferencException:
                work=0
                 
    def get_date(old_date):
        work=0
        while work==0:
            try:
               # new_day=browser.find_element_by_class_name('datepicker--label')
               new_day=WebDriverWait(browser, 10).until(EC.presence_of_element_located((By.CLASS_NAME, 'datepicker--label')))
               new_date=new_day.text
               if new_date!=old_date:
                    return [new_date]
                    work=1
            except StaleElementReferenceException:
                work=0
            
    def get_scores(old_scores):
        work=0
        while work==0:
            try:
                new_scores=browser.find_elements_by_class_name('score')
                new_score_list=[x.text for x in new_scores]
                if new_score_list!=old_scores:
                    return new_score_list
                    work=1
            except StaleElementReferenceException:
                work=0
            
   # def get_button():
   #     work=0
   #     while work<200:
   #         try: 
   #             print("trying to get back")
   #             back=browser.find_element_by_class_name('datepicker--prev')
   #             print(back)
   #             #back.click()
   #             back.send_keys(Keys.ENTER)
   #             work=1
   #         except StaleElementReferenceException:
   #             work+=1
    def next_page(tod):
        yesterday=tod-datetime.timedelta(1)
        yesterdate=yesterday.strftime('%Y-%m-%d')
        browser.get('https://app.whoop.com/athlete/24590/strain/1d/{}'.format(yesterdate))
        tod=yesterday
        return tod


    month_dict={'Jan':1,'Feb':2,'Mar':3,'Apr':4, 'May':5,'Jun':6,'Jul':7,'Aug':8,'Sep':9,'Oct':10,'Nov':11,'Dec':12}
    make_month=lambda x: month_dict[x[x.find(',')+1:x.find(',')+5].strip(" ")]
    make_day=lambda x: x[-4:-2]
    if not most_recent:
        most_recent=whoo.date[1].split(', ')[1].strip().lower()
    
    new_whoop=pd.DataFrame(columns=['strain','recovery','sleep_perf','sleep','rec_sleep','date','date_string', 
                            'activity_1','activity_1_score','activity_2','activity_2_score',
                           'activity_3','activity_3_score'])
    tod=datetime.datetime.today()
    num=0
    old_date='today'
    old_scores=['none']
    old_strain=['null']
    go_to_strain()
    new_date=get_date(old_date)
    print(new_date)
    while (new_date[0].split(', ')[1].strip().lower()!=most_recent and num<30):
        new_date=get_date(old_date)
        new_score=get_scores(old_scores)
        strains=get_activity_strain(old_strain,old_date)
        old_date=new_date
        old_scores=new_score
        old_strain=strains
        date_month=make_month(new_date[0])
        date_day=make_day(new_date[0])
        date_year= 2019
        date_string=[str(date_year) + "-" + str(date_month).strip(' ').zfill(2) + "-" + str(date_day).strip(' ').zfill(2)]

        new_whoop.loc[len(new_whoop)]=new_score[:5]+new_date+date_string+strains
       # get_button()
        tod=next_page(tod)
        num+=1
    print(new_whoop.shape, whoo.shape)
    all_whoop=pd.concat([new_whoop,whoo])
    wks_2.set_dataframe(all_whoop,(1,1))

    fix_df=wks_2.get_as_df(empty_value=np.nan)
    fix_df.dropna(how='all',inplace=True)
    fix_df.dropna(axis=1,how='all',inplace=True)
    fix_df.drop_duplicates('date_string',inplace=True)
    wks_2.set_dataframe(fix_df,(1,1))
    
    all_whoop=fix_df.copy(deep=True)
    all_whoop['recovery']=all_whoop['recovery'].astype(str).apply(lambda x: np.nan if '%' not in x else float(x[:len(x)-1])/100)
    all_whoop['sleep_perf']=all_whoop['sleep_perf'].astype(str).apply(lambda x: np.nan if '-' in x or "na" in x else float(x[:len(x)-1])/100)
    all_whoop['rec_color']=all_whoop.recovery.apply(lambda x: 'red' if x<.34 else ('yellow' if x<.67 else ('none' if np.isnan(x) else 'green') ))
    all_whoop.strain=all_whoop.strain.apply(lambda x: float(x) if x!="---" else 0)
    def time_to_dec(t):
        if ":" in t:
            hr=float(t[:t.find(':')])
            m=float(t[t.find(':')+1:])/60
            return hr+m
        else:
            return np.nan
    all_whoop.sleep=all_whoop.sleep.astype(str).apply(time_to_dec)
    all_whoop.rec_sleep=all_whoop.rec_sleep.astype(str).apply(time_to_dec)
    all_whoop['sleep_addition']=all_whoop.rec_sleep-7.75
    all_whoop['pday_rec']=all_whoop['recovery'].shift(-1)
    all_whoop['pday_rec_col']=all_whoop['rec_color'].shift(-1)
    for n in range(1,4):
        act_num="activity_{}_score".format(n)
        all_whoop[act_num]=all_whoop[act_num].apply(lambda x: np.nan if x=='null' else x)
    all_whoop['activity_total']=all_whoop[['activity_1_score','activity_2_score','activity_3_score']].apply(lambda x: sum([0 if y=='null' else (0 if np.isnan(y) else 1) for y in x ]),axis=1 )
    all_whoop['pday_acts']=all_whoop['activity_total'].shift(-1)
    all_whoop['pday_strain']=all_whoop['strain'].shift(-1)
    all_whoop['pday_sleep']=all_whoop.sleep.shift(-1)
    all_whoop['pday_sleep_perf']=all_whoop.sleep_perf.shift(-1)
    all_whoop['rolling_prev_2']=all_whoop.pday_sleep.rolling(2).mean()
    all_whoop['prev_strain_rec_gap']=all_whoop.pday_strain/all_whoop.pday_strain.max()-all_whoop.pday_rec
    
    act_1=all_whoop[['date','activity_1','activity_1_score']]
    act_1.columns=['date','activity','score']
    act_1['order']=1

    act_2=all_whoop[['date','activity_2','activity_2_score']]
    act_2.columns=['date','activity','score']
    act_2['order']=2
    act_2.dropna(inplace=True)

    act_3=all_whoop[['date','activity_3','activity_3_score']]
    act_3.columns=['date','activity','score']
    act_3['order']=3
    act_3.dropna(inplace=True)

    full_whoop=pd.concat([act_1,act_2,act_3])
    full_desc=all_whoop.drop(['activity_1','activity_2','activity_3','activity_1_score','activity_2_score','activity_3_score'],
                       axis=1)
    whoop_df=full_desc.merge(full_whoop, how ='left',left_on='date',right_on='date')
    whoop_df.head()
    
    wks_3.set_dataframe(whoop_df,(1,1))



get_strava('2018-04-01')
get_whoop('Tue, May 14th')
