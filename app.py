import streamlit as st
import sqlite3
import pandas as pd
from datetime import date
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
import os

st.set_page_config(page_title="Distributor Billing App", layout="wide")

DB = "distributor.db"
os.makedirs("invoices", exist_ok=True)

def db():
    return sqlite3.connect(DB, check_same_thread=False)

con = db()
cur = con.cursor()

cur.executescript("""
CREATE TABLE IF NOT EXISTS retailers(
 id INTEGER PRIMARY KEY,
 shop TEXT,
 owner TEXT,
 phone TEXT,
 credit_limit REAL
);

CREATE TABLE IF NOT EXISTS items(
 id INTEGER PRIMARY KEY,
 name TEXT,
 hsn TEXT,
 conversion REAL,
 price REAL,
 gst REAL,
 stock REAL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS orders(
 id INTEGER PRIMARY KEY,
 retailer_id INTEGER,
 order_date TEXT,
 status TEXT
);

CREATE TABLE IF NOT EXISTS order_items(
 order_id INTEGER,
 item_id INTEGER,
 qty REAL,
 unit TEXT
);

CREATE TABLE IF NOT EXISTS invoices(
 id INTEGER PRIMARY KEY,
 order_id INTEGER,
 taxable REAL,
 gst REAL,
 total REAL,
 invoice_date TEXT
);

CREATE TABLE IF NOT EXISTS payments(
 id INTEGER PRIMARY KEY,
 retailer_id INTEGER,
 invoice_id INTEGER,
 amount REAL,
 mode TEXT,
 pay_date TEXT
);
""")
con.commit()

def to_box(qty, unit, conv):
    return qty if unit == "BOX" else qty / conv

def invoice_pdf(inv_id, shop, total):
    f = f"invoices/INV_{inv_id}.pdf"
    c = canvas.Canvas(f, pagesize=A4)
    c.drawString(50, 800, "TAX INVOICE")
    c.drawString(50, 770, f"Invoice No: {inv_id}")
    c.drawString(50, 750, f"Retailer: {shop}")
    c.drawString(50, 730, f"Date: {date.today()}")
    c.drawString(50, 700, f"Total Amount: ₹ {total}")
    c.save()
    return f

st.sidebar.title("📦 Distributor App")
menu = st.sidebar.radio("Menu", [
    "Retailers","Items","New Order","Approve Orders","Payments","Outstanding","Stock"
])

if menu == "Retailers":
    st.title("🏪 Retailers")
    shop = st.text_input("Shop Name")
    owner = st.text_input("Owner Name")
    phone = st.text_input("Phone")
    credit = st.number_input("Credit Limit", 0.0)

    if st.button("Save Retailer"):
        cur.execute("INSERT INTO retailers VALUES(NULL,?,?,?,?)",(shop,owner,phone,credit))
        con.commit()
        st.success("Retailer Added")

    st.dataframe(pd.read_sql("SELECT * FROM retailers", con))

elif menu == "Items":
    st.title("📦 Items")
    name = st.text_input("Item Name")
    hsn = st.text_input("HSN")
    conv = st.number_input("1 BOX =", 24.0)
    price = st.number_input("Sale Price")
    gst = st.number_input("GST %")

    if st.button("Save Item"):
        cur.execute("INSERT INTO items VALUES(NULL,?,?,?,?,?,0)",
                    (name,hsn,conv,price,gst))
        con.commit()
        st.success("Item Added")

    st.dataframe(pd.read_sql("SELECT * FROM items", con))

elif menu == "New Order":
    st.title("📝 New Order")
    retailers = pd.read_sql("SELECT * FROM retailers", con)
    items = pd.read_sql("SELECT * FROM items", con)

    if len(retailers)==0 or len(items)==0:
        st.info("Add retailers and items first")
    else:
        r = st.selectbox("Retailer", retailers["shop"])
        item = st.selectbox("Item", items["name"])
        qty = st.number_input("Qty")
        unit = st.selectbox("Unit", ["BOX","PCS"])

        if st.button("Save Order"):
            rid = retailers[retailers.shop==r]["id"].values[0]
            cur.execute("INSERT INTO orders VALUES(NULL,?,?,?)",(rid,date.today(),"Pending"))
            oid = cur.lastrowid

            it = items[items.name==item].iloc[0]
            cur.execute("INSERT INTO order_items VALUES(?,?,?,?)",(oid,it.id,qty,unit))
            con.commit()
            st.success("Order Booked")

elif menu == "Approve Orders":
    st.title("✅ Approve Orders")
    orders = pd.read_sql("SELECT * FROM orders WHERE status='Pending'", con)

    if len(orders)==0:
        st.info("No pending orders")
    else:
        oid = st.selectbox("Order ID", orders["id"])
        if st.button("Approve & Invoice"):
            oi = pd.read_sql("SELECT * FROM order_items WHERE order_id=?", con, params=[oid])
            taxable = 0
            gst_amt = 0

            for _,x in oi.iterrows():
                it = pd.read_sql("SELECT * FROM items WHERE id=?", con, params=[x.item_id]).iloc[0]
                qb = to_box(x.qty, x.unit, it.conversion)
                amt = qb * it.price
                gst_amt += amt * it.gst / 100
                taxable += amt
                cur.execute("UPDATE items SET stock=stock-? WHERE id=?",(qb,it.id))

            total = taxable + gst_amt
            cur.execute("INSERT INTO invoices VALUES(NULL,?,?,?,?,?)",(oid,taxable,gst_amt,total,date.today()))
            cur.execute("UPDATE orders SET status='Approved' WHERE id=?",(oid,))
            con.commit()

            inv_id = cur.lastrowid
            shop = pd.read_sql("SELECT shop FROM retailers WHERE id=(SELECT retailer_id FROM orders WHERE id=?)",
                               con,params=[oid]).iloc[0,0]
            pdf = invoice_pdf(inv_id, shop, total)
            with open(pdf,"rb") as f:
                st.download_button("Download Invoice",f,file_name=pdf)

elif menu == "Payments":
    st.title("💰 Payments")
    retailers = pd.read_sql("SELECT * FROM retailers", con)
    r = st.selectbox("Retailer", retailers["shop"])
    amt = st.number_input("Amount")
    mode = st.selectbox("Mode",["Cash","UPI","Bank"])

    if st.button("Save Payment"):
        rid = retailers[retailers.shop==r]["id"].values[0]
        cur.execute("INSERT INTO payments VALUES(NULL,?,?,?,?)",
                    (rid,None,amt,mode,date.today()))
        con.commit()
        st.success("Payment Saved")

elif menu == "Outstanding":
    st.title("📊 Outstanding")
    query = """
    SELECT r.shop,
           IFNULL(SUM(i.total),0) - IFNULL(SUM(p.amount),0) AS outstanding
    FROM retailers r
    LEFT JOIN orders o ON r.id=o.retailer_id
    LEFT JOIN invoices i ON o.id=i.order_id
    LEFT JOIN payments p ON r.id=p.retailer_id
    GROUP BY r.id
    """
    st.dataframe(pd.read_sql(query, con))

elif menu == "Stock":
    st.title("📦 Stock Summary")
    st.dataframe(pd.read_sql("SELECT name, stock FROM items", con))