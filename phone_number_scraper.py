import argparse
import sys
import csv
import logging
import urlparse
import re
from bs4 import BeautifulSoup as bs
from selenium import webdriver
import selenium.common.exceptions

parser = argparse.ArgumentParser(description='Scrape phone numbers from links.')
parser.add_argument('--csv', dest='inputfn', type=str,
                    help="Input spreadsheets with links.")
parser.add_argument('--log', type=str, dest='logfile', default='scraper.log',
                    help="Log destination")
parser.add_argument('--out', dest='outputfn', type=str,
                    help="Input spreadsheets with links.")
parser.add_argument('--maxlinks', dest='max_links', type=int, default=10,
                    help="How many links to crawl through from the site's home page until quitting.")
parser.add_argument('--wait', dest='wait', type=int, default=60,
                    help="How many seconds to wait for a page to load until giving up.")
args = parser.parse_args()

##set up logging
logger = logging.getLogger()
logger.setLevel(logging.DEBUG)
fh = logging.FileHandler(args.logfile)
fh.setLevel(logging.DEBUG)
ch = logging.StreamHandler()
ch.setLevel(logging.ERROR)
ch_info = logging.StreamHandler()
ch_info.setLevel(logging.INFO)
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
ch.setFormatter(formatter)
fh.setFormatter(formatter)
console_formatter = logging.Formatter('%(asctime)s - %(message)s')
ch_info.setFormatter(console_formatter)
logger.addHandler(ch)
logger.addHandler(fh)
logger.addHandler(ch_info)

def normalize_url(url):
    """
    Will add 'www' and 'http' to urls where these are missing.
    Input: string 
    Output: string 
    """
    url = url.lower()
    if not url.startswith('www.'):
	url = 'www.'+url
    parsed_url = ['http', url, '', '', '', '']
    return urlparse.urlunparse(parsed_url)

##words and bigrams that may be associated with a page that has contact information
priority_re = ur'about|more|faq|contact|info|reach|who we are|whoweare|whowe|who we|whatwe|what we|locate|find out|findout|learn|customer|service|operator|speakwith|speak with|talk to|talkto'
priority_re = re.compile(priority_re, re.IGNORECASE)

##regexp that matches a phone number of any format
phone_re = ur'(?:(?<=[\s\:\(])|\A)(?:(?:\+?1\s*(?:[.-]\s*)?)?(?:\(\s*([2-9]1[02-9]|[2-9][02-8]1|[2-9][02-8][02-9])\s*\)|([2-9]1[02-9]|[2-9][02-8]1|[2-9][02-8][02-9]))\s*(?:[.-]\s*)?)?([2-9]1[02-9]|[2-9][02-9]1|[2-9][02-9]{2})\s*(?:[.-]\s*)?([0-9]{4})(?:\s*(?:#|x\.?|ext\.?|extension)\s*(\d+))?'
phone_re = re.compile(phone_re, re.UNICODE)
def number_finder(text):
    assert isinstance(text, basestring)
    return phone_re.findall(text)

class PhoneScraper:
    """
    This class will visit a list of URLs read from a spreadsheet.
    It will emit a new spreadsheet appending the phone numbers it finds
    at each URL to the appropriate row of the spreadsheet
    """
    def __init__(self, ifn, ofn, max_links = 10, wait = 60):
	self.ifn = ifn
	self.ofn = ofn
	self.numbers = {}
	self.max_links = max_links

	self.main_driver = webdriver.Firefox()
	self.main_driver.implicitly_wait(wait)
	logger.info("Webdriver successfully initiated.")

	self.read_csv()
	self.outputcsv = open(ofn, 'w')
	self.writer = csv.writer(self.outputcsv)

    def is_internal(self, url):
	"""
	Detect if a URL belongs to the same domain as the current page.
	Returns: bool
	"""
	current_page = urlparse.urlparse(self.main_driver.current_url.lower())
	new_page = urlparse.urlparse(url.lower())
	if current_page.netloc == new_page.netloc and current_page.scheme == new_page.scheme: 
	    return True
	else:
	    return False


    def link_priority(self, ele):
	"""
	Get a priority score for links so they can be crawled in order of importance.
	Mainly we want to visit anything that looks like a "contact us" page right away.
	Returns: False or int
	"""
	try:
	    href = ele.get_attribute('href')
	except:
	    return False
	if not href: return False
	if not self.is_internal(href): 
	    return False
	phref = urlparse.urlparse(href)
	if priority_re.search(phref.path) or priority_re.search(ele.text):
	    return 1
	else:
	    return 2

    def read_csv(self):
	"""
	Read in the input CSV that contains the URLs to visit.
	Assumes the URLs are in the first column of the spreadsheet.
	"""
	self.input_data = {}
	with open(self.ifn, 'rb') as csvfile:
	    logger.debug("Opened %s.", args.inputfn)
	    dialect = csv.Sniffer().sniff(csvfile.read(1024))
	    csvfile.seek(0)
	    reader = csv.reader(csvfile, dialect=dialect)
	    for row in reader:
		self.input_data[row[0]] = row
	    logger.debug("There are (%s) entries to process." % len(self.input_data) )

    def update_csv(self):
	"""
	Write all URL/phone number pairs that exist in self.numbers to the output spreadsheet.
	"""
	scraped_numbers = self.numbers.items()
	for k,v in scraped_numbers:
	    row = self.input_data[k] 
	    if isinstance(v, list):
		row.extend(v)
	    else:
		row.append('None Found')
	    self.writer.writerow(row )
	    del self.numbers[k]

    def scrape_phone_numbers(self):
	"""
	Scrape all phone numbers from the currently open page and save them to self.numbers.
	"""
	all_numbers = {}
	try:
	    soup = bs(self.main_driver.page_source)
	except selenium.common.exceptions.UnexpectedAlertPresentException:
	    try:
		alert = self.main_driver.switch_to_alert()
		alert.accept()
		soup = bs(self.main_driver.page_source)
	    except Exception as e:
		logger.error("Exception (%s) triggered when extracting source from (%s)" % (e, self.main_driver.current_url) )
		return False
	except Exception as e:
	    logger.error("Exception (%s) triggered when extracting source from (%s)" % (e, self.main_driver.current_url) )
	    return False
	extracted_strings = soup.find_all(lambda x: x.name != 'script' and x.name != 'style' and x.name != 'noscript' and x.name != 'iframe', text=lambda x: True)
	for extracted_string in extracted_strings:
	    for extracted_number in phone_re.findall(extracted_string.text):
		extracted_number = '-'.join(extracted_number).encode('ascii', 'ignore')
		extracted_number = re.sub('-{2,}|\A-|-\Z', '', extracted_number )
		if len(extracted_number) >= 12:
		    all_numbers[extracted_number] = extracted_number
	if len(all_numbers):
	    logger.info("Found %s phone numbers at (%s):\n%s" % (len(all_numbers), self.main_driver.current_url, all_numbers.values()) )
	    return all_numbers.values()
	else:
	    logger.debug("Found %s phone numbers at (%s)" % (len(all_numbers), self.main_driver.current_url) )
	    return False

    def yield_links(self):
	"""
	Yield all links on the current page.
	Returns: List of URLs
	"""
	try:
	    all_links = self.main_driver.find_elements_by_tag_name('a')
	except Exception as e:
	    logger.info("Unable to locate any links at (%s), triggered exception (%s)." % (self.main_driver.current_url, e) )
	    return []
	internal_links = {}
	for ele in all_links:
	    priority = self.link_priority(ele)
	    if priority:
		href = ele.get_attribute('href').lower()
		if priority == 1: 
		    logger.info("High priority link discovered. URL: (%s). Link text: (%s). Priority: (%s)." % (href, ele.text, priority) )
		if href not in internal_links:
		    internal_links[href] = priority
	internal_links = internal_links.items()
	internal_links.sort( key = lambda x: x[1] )
	logger.info("(%s) links on page" % len(internal_links) )
	return [ x[0] for x in internal_links ]

    def find_numbers(self):
	"""
	Iterate through input spreadsheet, load a URL from the spreadsheet, open it in the browser, try to extract phone numbers.
	If that fails, follow links from the homepage until we find a page with a phone number on it, then quit.
	Emit all found numbers to the output spreadsheet.
	"""
	for raw_url in self.input_data.keys():
	    url = normalize_url(raw_url)
	    logger.info("Processing (%s)." % (url) )
	    try:
		self.main_driver.get(url)
	    except selenium.common.exceptions.WebDriverException:
		logger.info("Failed to GET (%s)." % (url) )
		self.numbers[raw_url] = ['Could not access page']
		self.update_csv()
		continue
	    except Exception as e:
		logger.error("Exception (%s) raised when trying to access (%s)" % (e, link) )
		continue
	    self.numbers[raw_url] = self.scrape_phone_numbers()
	    if self.numbers[raw_url]: 
		self.update_csv()
		continue
	    links = self.yield_links()
	    links_tried = 0
	    for link in links:
		links_tried += 1
		try:
		    self.main_driver.get(link)
		except selenium.common.exceptions.WebDriverException:
		    logger.info("Failed to GET (%s)." % (link) )
		    continue
		except Exception as e:
		    logger.error("Exception (%s) raised when trying to access (%s)" % (e, link) )
		    continue
		logger.info("Spider crawling to (%s) from (%s)." % ( link, url) )
		self.numbers[raw_url] = self.scrape_phone_numbers()
		if self.numbers[raw_url]: break
		if links_tried >= self.max_links: break
	    self.update_csv()

    def __enter__(self): return self
    def __exit__(self, type, value, traceback):
	self.main_driver.close()
	self.outputcsv.close()

if __name__ == '__main__': 
    with PhoneScraper(args.inputfn, args.outputfn, max_links = args.max_links, wait = args.wait) as scraper:
	scraper.find_numbers()


