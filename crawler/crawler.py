import requests
from bs4 import BeautifulSoup
import re
import os
import time
import json
import base64
from urllib.parse import urljoin, unquote

class SimpleOSGeoWikiCrawler:
    def __init__(self, base_url="https://wiki.osgeo.org", output_dir="../wiki_dump"):
        self.base_url = base_url
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/91.0'
        })
        self.output_dir = output_dir
        self.visited = set()
        self.url_map = {}  # Mapping between filenames and URLs
        self.url_map_file = os.path.join(output_dir, "url_map.json")
        
        # Create output directory
        os.makedirs(output_dir, exist_ok=True)
        
        # Load existing URL map if it exists
        if os.path.exists(self.url_map_file):
            try:
                with open(self.url_map_file, 'r', encoding='utf-8') as f:
                    self.url_map = json.load(f)
                print(f"Loaded {len(self.url_map)} URLs from existing map")
            except Exception as e:
                print(f"Error loading URL map: {e}")
    
    def get_all_pages(self):
        """Get all wiki page links from the Special:AllPages page"""
        all_pages = []
        url = f"{self.base_url}/wiki/Special:AllPages"
        
        while url:
            print(f"Fetching page list from: {url}")
            response = self.session.get(url)
            if response.status_code != 200:
                print(f"Failed to fetch {url}, status code: {response.status_code}")
                break
                
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # Extract links to actual wiki pages
            content_div = soup.find('div', {'class': 'mw-allpages-body'})
            if content_div:
                for link in content_div.find_all('a'):
                    page_url = urljoin(self.base_url, link.get('href'))
                    if '/wiki/' in page_url and not any(x in page_url for x in ['Special:', 'File:', 'Category:', 'Template:']):
                        all_pages.append(page_url)
                        
            # Find the "next page" link
            next_link = soup.find('a', string=re.compile(r'Next page|Next'))
            url = urljoin(self.base_url, next_link.get('href')) if next_link else None
            
            # Be polite
            time.sleep(1)
            
        print(f"Found {len(all_pages)} wiki pages")
        return all_pages
    
    def url_to_filename(self, url):
        """Convert URL to a suitable filename using base64 encoding"""
        # Extract the page name from the URL
        page_name = url.split('/wiki/')[-1]
        
        # Use base64 encoding to ensure uniqueness and avoid special chars
        # We'll strip padding characters (=) which aren't needed for filenames
        encoded = base64.urlsafe_b64encode(page_name.encode()).decode().rstrip('=')
        
        return encoded
    
    def is_already_downloaded(self, url):
        """Check if a page is already downloaded"""
        # Check if URL exists in our map
        for filename, stored_url in self.url_map.items():
            if stored_url == url:
                return os.path.exists(os.path.join(self.output_dir, filename))
        
        # If URL not in map, check by generating the filename
        filename = self.url_to_filename(url)
        return os.path.exists(os.path.join(self.output_dir, filename))
    
    def extract_page(self, url):
        """Extract a wiki page"""
        if url in self.visited:
            return None
            
        self.visited.add(url)
        
        # Skip if already downloaded
        if self.is_already_downloaded(url):
            print(f"Skipping already downloaded: {url}")
            return None
            
        print(f"Fetching content from: {url}")
        
        try:
            response = self.session.get(url)
            if response.status_code != 200:
                print(f"Failed to fetch {url}, status code: {response.status_code}")
                return None
                
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # Extract title
            title_element = soup.find('h1', {'id': 'firstHeading'})
            title = title_element.text.strip() if title_element else ""
            
            # Extract main content
            content_div = soup.find('div', {'id': 'mw-content-text'})
            if not content_div:
                print(f"No content found for {url}")
                return None
                
            # Extract text content
            content = content_div.get_text('\n', strip=True)
            
            # Extract categories
            categories = []
            catlinks_div = soup.find('div', {'id': 'catlinks'})
            if catlinks_div:
                for link in catlinks_div.find_all('a'):
                    cat_name = link.text.strip()
                    if cat_name and not cat_name.startswith("Category:"):
                        categories.append(cat_name)
            
            return {
                'title': title,
                'url': url,
                'content': content,
                'categories': categories
            }
            
        except Exception as e:
            print(f"Error processing {url}: {e}")
            return None
            
        finally:
            # Be polite
            time.sleep(2)
    
    def save_page(self, data):
        """Save page to a file based on URL"""
        if not data:
            return
        
        url = data['url']
        filename = self.url_to_filename(url)
        filepath = os.path.join(self.output_dir, filename)
        
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(f"URL: {url}\n")
            f.write(f"Title: {data['title']}\n")
            
            # Write categories
            if data['categories']:
                f.write("\nCategories:\n")
                for category in data['categories']:
                    f.write(f"- {category}\n")
            
            f.write("\nContent:\n")
            f.write(data['content'])
        
        # Add to URL map
        self.url_map[filename] = url
        
        # Save the URL map every 10 pages
        if len(self.url_map) % 10 == 0:
            self._save_url_map()
            
        print(f"Saved {data['title']} to {filepath}")
    
    def _save_url_map(self):
        """Save the URL mapping to a JSON file"""
        try:
            with open(self.url_map_file, 'w', encoding='utf-8') as f:
                json.dump(self.url_map, f, indent=2)
        except Exception as e:
            print(f"Error saving URL map: {e}")
    
    def run(self, max_pages=None):
        """Run the crawler"""
        page_urls = self.get_all_pages()
        
        if max_pages:
            page_urls = page_urls[:max_pages]
        
        total_pages = len(page_urls)
        processed = 0
        skipped = 0
        start_time = time.time()
        
        for i, url in enumerate(page_urls):
            # Show progress
            if i % 10 == 0 and i > 0:
                elapsed = time.time() - start_time
                pages_per_second = i / elapsed if elapsed > 0 else 0
                remaining = (total_pages - i) / pages_per_second if pages_per_second > 0 else 0
                print(f"Progress: {i}/{total_pages} pages - {pages_per_second:.2f} pages/sec - ETA: {remaining:.0f} seconds")
            
            data = self.extract_page(url)
            if data:
                self.save_page(data)
                processed += 1
            else:
                skipped += 1
        
        # Make sure to save the URL map at the end
        self._save_url_map()
        
        print(f"Crawling complete. Processed {processed} pages, skipped {skipped} pages.")

if __name__ == "__main__":
    crawler = SimpleOSGeoWikiCrawler()
    crawler.run(max_pages=None)