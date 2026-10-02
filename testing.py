import undetected_chromedriver as webdriver
import time

options = webdriver.ChromeOptions()

options.add_argument(
    "--user-data-dir=/Users/app/Library/Application Support/Google/Chrome"
)
options.add_argument("--profile-directory=Profile 10")

driver = webdriver.Chrome(options=options)

print("Started")

url = "https://www.google.com/recaptcha/api2/demo"

print("Opening:", url)

driver.get(url)

print("URL:", driver.current_url)
print("TITLE:", driver.title)

time.sleep(5)

print(
    driver.execute_script("""
        const el = document.querySelector('.g-recaptcha');

        return {
            readyState: document.readyState,
            recaptchaCount: document.querySelectorAll('.g-recaptcha').length,
            sitekey: el ? el.getAttribute('data-sitekey') : null,
            responseCount: document.querySelectorAll('#g-recaptcha-response').length
        };
    """)
)

time.sleep(5)
driver.quit()