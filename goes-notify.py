#!/usr/bin/env python

import argparse
import json
import logging
import sys
import requests
import time
import smtplib
import os
from email.mime.text import MIMEText

from datetime import datetime
from os import path

foundApts = {}
allLocationsList = []

GOES_URL_FORMAT = 'https://ttp.cbp.dhs.gov/schedulerapi/slots?orderBy=soonest&limit=3&locationId={0}&minimum=1'

def send_email(body, sender, recipients, password):
    try:
        subject = 'Global Entry Interview found'
        msg = MIMEText(body)
        msg['Subject'] = subject
        msg['From'] = sender
        msg['To'] = ', '.join(recipients)
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as smtp_server:
            smtp_server.login(sender, password)
            smtp_server.sendmail(sender, recipients, msg.as_string())
        logging.debug('Message sent!')
    except (AttributeError):
        logging.warning('Error occured when sending an email')

def filter(settings, dtp):
    latest_date = datetime.strptime(settings['latest_interview_date'], '%B %d, %Y')
    if latest_date <= dtp:
        return False
    if dtp.hour <= settings['weekday_filter_hour']:
        return False
    if dtp.weekday() in settings['weekday_filter_day']:
        return False
    return True

def search(settings):
    for location in settings['enrollment_location_id']:
        try:
            # obtain the json from the web url
            data = requests.get(GOES_URL_FORMAT.format(location)).json()

            # parse the json
            if not data:
                # Clear the found appointments, because they're all gone
                logging.debug('No tests available at %s' % get_location_string(location))
                foundApts[location] = []
                continue

            dates = []
            for o in data:
                if o['active']:
                    dt = o['startTimestamp'] #2017-12-22T15:15
                    dtp = datetime.strptime(dt, '%Y-%m-%dT%H:%M')
                    if filter(settings, dtp):
                        dates.append(dtp.strftime('%A, %B %d @ %I:%M%p'))

            # Add new dates
            newApts = []
            for date in dates:
                if date not in foundApts[location]:
                    # first time seeing that date, so add it to the lists
                    foundApts[location].append(date)
                    newApts.append(date)

            # Clean up unavailable appointments
            for apt in foundApts[location]:
                if apt not in dates:
                    logging.info("Removing %s at %s" % (apt, get_location_string(location)))
                    foundApts[location].remove(apt)

            if dates and not settings['no_spamming']:
                send_notification(settings, location, dates)
            elif newApts:
                send_notification(settings, location, newApts)

        except OSError:
            logging.critical('Something went wrong when trying to obtain the openings')

def send_notification(settings, location, dates):
    msg = 'Found new appointment(s) in location %s on %s!' % (get_location_string(location), '\n'.join(dates))
    logging.info(msg)

    send_email(msg, settings['gmail_sender'], settings['gmail_recipients'], settings['gmail_app_password'])

def get_location_string(location):
    return next((item for item in allLocationsList if item["id"] == int(location)), None)['name']

def _check_settings(config):
    required_settings = (
        'latest_interview_date',
        'enrollment_location_id',
        'poll_interval',
        'gmail_recipients',
        'gmail_sender',
        'gmail_app_password',
        'weekday_filter_hour'
    )

    for setting in required_settings:
        if not config.get(setting):
            raise ValueError('Missing setting %s in config.json file.' % setting)

if __name__ == '__main__':
    # Configure Basic Logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(levelname)s: %(asctime)s %(message)s',
        datefmt='%m/%d/%Y %I:%M:%S %p',
        stream=sys.stdout,
    )

    pwd = path.dirname(__file__)

    # Parse Arguments
    parser = argparse.ArgumentParser(description='Command line script to check for goes openings.')
    parser.add_argument('--config', dest='configfile', default='%s/config.json' % pwd, help='Config file to use (default is config.json)')
    arguments = vars(parser.parse_args())
    logging.info('config file is:' + arguments['configfile'])

    # Load Settings
    try:
        with open(arguments['configfile']) as json_file:
            settings = json.load(json_file)
            logging.info(settings)

            # merge args into settings IF they're True
            for key, val in arguments.items():
                if not arguments.get(key): continue
                settings[key] = val

            settings['configfile'] = arguments['configfile']
            _check_settings(settings)
    except Exception as e:
        logging.error('Error loading settings from config.json file: %s' % e)
        sys.exit()

    # Configure File Logging
    if settings.get('logfile'):
        handler = logging.FileHandler('%s/%s' % (pwd, settings.get('logfile')))
        handler.setFormatter(logging.Formatter('%(levelname)s: %(asctime)s %(message)s'))
        handler.setLevel(logging.DEBUG)
        logging.getLogger('').addHandler(handler)

    logging.debug(settings)

    with open('ttp.cbp.dhs.gov.json') as json_file:
        allLocationsList = json.load(json_file)

    for location in settings['enrollment_location_id']:
        foundApts[location] = []

    # Search until the day of the interview
    while datetime.strptime(settings['latest_interview_date'], '%B %d, %Y') > datetime.now():
        search(settings)
        time.sleep(settings['poll_interval'])
