TCGplayer Daily Price Tracker
This Python script automates the process of tracking prices for collectible trading cards on TCGplayer.com. It runs daily, scrapes data for multiple products, records the history in CSV files, and generates a single, combined PDF report with advanced visualizations and a summary of the day's market activity.

Features
Multi-Product Tracking: Easily track multiple products by adding their URLs to a list.

Automated Data Scraping: Uses Selenium to control a web browser, ensuring that all dynamically loaded (JavaScript) content is captured correctly.

Historical Data Logging: Saves the daily scraped data into individual .csv files for each product, creating a historical price database.

Combined PDF Reporting: Generates a single, professional PDF report (TCGplayer_Combo_Report.pdf) with:

An Executive Summary page comparing all tracked products at a glance.

Color-Coded Price Changes on the summary page (green for up, red for down).

Detailed Individual Pages for each product.

Advanced Data Visualizations, including a 7-day moving average, recent sale scatter plots, and a bar chart for the number of sellers.

Task Scheduling: Can be easily automated to run at a specific time every day using Windows Task Scheduler.

Sample Report Output
The generated PDF report includes a summary page and detailed pages for each product.

Summary Page:
 <-- Replace with an actual screenshot of your summary page

Detailed Product Page:
 <-- Replace with an actual screenshot of a detailed product page

Setup & Installation
Follow these steps to get the project running.

1. Prerequisites
Python 3.9 or newer

Google Chrome browser installed

2. Clone the Repository
git clone <your-repository-url>
cd <your-repository-directory>

3. Install Required Libraries
This project requires several Python libraries. You can install them all with pip:

pip install pandas matplotlib beautifulsoup4 selenium webdriver-manager fpdf2

For Python 3.12+ Users:
The distutils package was removed from Python 3.12. If you encounter a ModuleNotFoundError for distutils when running the script, you also need to install setuptools:

pip install setuptools

Configuration
Open the dailyreport.py script and edit the URLS list to include the TCGplayer product pages you want to track.

# --- Configuration ---
# Add as many product URLs as you want to this list
URLS = [
    '[https://www.tcgplayer.com/product/624679/](https://www.tcgplayer.com/product/624679/)',
    '[https://www.tcgplayer.com/product/623628](https://www.tcgplayer.com/product/623628)',
    # Add more URLs here
]

Running the Script
To run the script manually, navigate to the project directory in your terminal and execute the following command:

python dailyreport.py

The script will then:

Launch a headless Chrome browser.

Visit each URL in your list and scrape the data.

Update the corresponding .csv file for each product.

Generate the TCGplayer_Combo_Report.pdf file in the same directory.

Scheduling (Windows)
You can use the Windows Task Scheduler to run this script automatically every day.

Open Command Prompt as an Administrator.

Find your Python path by running:

where python

(e.g., C:\Users\YourUser\AppData\Local\Programs\Python\Python311\python.exe)

Find your script's full path (e.g., D:\Projects\tcgplayer\dailyreport.py).

Run the schtasks command, replacing the placeholder paths with your actual paths. The following example schedules the task for 8:00 AM daily.

schtasks /create /tn "TCGplayer Daily Report" /tr "'C:\path\to\your\python.exe' 'D:\path\to\your\dailyreport.py'" /sc DAILY /st 08:00

This creates a task that will run in the background at the specified time each day.
