import Solve

# Solve ReCaptcha
result = Solve.ReCaptcha(
    '6Lf26sUnAAAAAIKLuWNYgRsFUfmI-3Lex3xT5N-s', # siteKey
    'https://2captcha.com/demo/recaptcha-v2-enterprise' # URL Website
)
print(result)



# # Solve HCaptcha
# result = Solve.HCaptcha(
#     'a5f74b19-9e45-40e0-b45d-47ff91b7a6c2', # siteKey
#     'https://accounts.hcaptcha.com/demo' # URL Website
# )
# print(result)
