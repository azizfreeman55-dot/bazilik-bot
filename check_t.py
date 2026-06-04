import sys
sys.path.insert(0, '.')
from langs import t

lang = "uz_latin"
print(t(lang, "orders_closed"))
print(t(lang, "no_menu"))
print(t(lang, "order_accepted"))