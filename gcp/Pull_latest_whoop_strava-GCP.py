import requests
import pandas as pd
from selenium import webdriver
from selenium.webdriver.common.keys import Keys
from bs4 import BeautifulSoup as BS
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import StaleElementReferenceException
from selenium.webdriver.chrome.options import Options 
import configparser
import time
import datetime
import swagger_client
from swagger_client.rest import ApiException
import pygsheets
import math


#authorization
gc = pygsheets.authorize(outh_file='client_secret.json')
file = 'Activity data'
sh = gc.open(file)

wks_1 = sh[0]
strav=wks_1.get_as_df(empty_value=np.nan)
strav.dropna(how='all',inplace=True)

wks_2=sh[1]
whoo=wks_2.get_as_df(empty_value=np.nan)
whoo.dropna(how='all',inplace=True)
whoo.dropna(axis=1,how='all',inplace=True)


def get_strava(last_date=False):
    ## Getting log in info
    config = configparser.ConfigParser()
    config.read("strava.ini")
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
    new_acts=pd.DataFrame([dicts[key] for key in index],index=index)
    if len(strav)==0:
        wks_1.set_dataframe(new_acts,(1,1))
    else:
        all_acts=pd.concat([new_acts,strav])
        all_acts.drop_duplicates(inplace=True)
        wks_1.set_dataframe(all_acts,(1,1))

get_strava()

def get_whoop(most_recent=False):
    
    config = configparser.ConfigParser()
    config.read("strava.ini")
    
    w='https://app.whoop.com/login'
    
    chrome_options = Options()  
    chrome_options.add_argument("--headless")  
    chrome_options.binary_location = '/usr/bin/chromium'

    browser=webdriver.Chrome('/usr/bin/chromedriver',chrome_options=chrome_options)
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
                new_day=browser.find_element_by_class_name('datepicker--label')
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
            
    def get_button():
        work=0
        while work==0:
            try: 
                back=browser.find_element_by_class_name('datepicker--prev')
                back.click()
                work=1
            except StaleElementReferenceException:
                work=0

    if not most_recent:
        most_recent=whoo.date[0].split(', ')[1]
    
    new_whoop=pd.DataFrame(columns=['strain','recovery','sleep_perf','sleep','rec_sleep','date', 
                            'activity_1','activity_1_score','activity_2','activity_2_score',
                           'activity_3','activity_3_score'])
    num=0
    old_date='today'
    old_scores=['none']
    old_strain=['null']
    go_to_strain()
    new_date=get_date(old_date)
    while (new_date[0].split(', ')[1].strip().lower()!=most_recent and num<20):
        new_date=get_date(old_date)
        new_score=get_scores(old_scores)
        strains=get_activity_strain(old_strain,old_date)
        old_date=new_date
        old_scores=new_score
        old_strain=strains
        new_whoop.loc[len(new_whoop)]=new_score[:5]+new_date+strains
        get_button()
        num+=1
    print(new_whoop.columns, whoo.columns)
    all_whoop=pd.concat([new_whoop,whoo])
    all_whoop.drop_duplicates(inplace=True)
    if len(all_whoop)>=len(whoo):
        wks_2.set_dataframe(all_whoop,(1,1))

get_whoop()