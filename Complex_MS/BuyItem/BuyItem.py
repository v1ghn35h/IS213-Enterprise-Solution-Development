from flask import Flask, request, jsonify
from flask_cors import CORS

import os
import sys
from os import environ

import requests
from invokes import invoke_http

import amqp_setup
import pika
import json

app = Flask(__name__)
CORS(app)

listing_URL = environ.get('listing_URL') or "http://localhost:5002"
payment_URL = environ.get('payment_URL') or "http://localhost:5005/payment"
cart_URL = environ.get('cart_URL') or "http://127.0.0.1:5003"
order_URL = environ.get('order_URL') or "http://127.0.0.1:5004"
rabbitMQhostname = environ.get('rabbit_host') or "localhost"


@app.route("/buy_item", methods=['POST'])
def buy_item():
    data = request.json
    # shoppingCart = data['dataObj']
    userId = data['userId']
    card_details = data['cardDetails']
    cardHolderName = data['cardName']
    try:
        cartQuery = {
            "buyerID": userId
        }
        # invoke cartMS to get the cart
        getCartResponse = invoke_http(
            cart_URL + "/get_cart", method='GET', json=cartQuery)
        # print("TEST getCartResponse (START)")
        # print(getCartResponse)
        # print("TEST getCartResponse (END)")
        shoppingCart = getCartResponse['data']["cart_list"]
        # print("TEST shoppingCart (START)")
        # print (shoppingCart)
        # print("TEST shoppingCart (END)")

        manySellerID = []
        for eachItem in shoppingCart:
            product_ID = eachItem['productID']
            productName = eachItem['itemName']

            listing_ms_url = f"{listing_URL}/products/{product_ID}"
            listingResponse = requests.get(listing_ms_url)
            data = listingResponse.json()

            checkProduct = data['data']['product']
            # print("TEST START")
            # # print (eachItem)
            # print(checkProduct)
            # print ("TEST END")

            sellerID = checkProduct['sellerID']
            manySellerID.append(sellerID)

            checkOuantity = checkProduct['quantity']
            currentQuantity = eachItem['inputQuantity']
            # print ("TEST START")
            # print (checkOuantity)
            # print (currentQuantity)
            # print ("TEST END" )
            if currentQuantity > checkOuantity:
                return jsonify({
                    'code': 400,
                    'error': f"Checkout error: {productName} is currently unavailable due to not enough inventory quantity",
                }),
                400

        combinedData = {"buyerID": userId, "sellerIDs": manySellerID, "dataObj": shoppingCart,
                        "cardDetails": card_details, "cardName": cardHolderName}
        # print("TEST CD (START)")
        # print(combinedData)
        # print("TEST CD (END)")
        processOrderResult = processOrder(combinedData)
        print("TEST processOrderResult (START)")
        print(processOrderResult)
        print("TEST processOrderResult (END)")

        return jsonify(processOrderResult), processOrderResult["code"]

    except Exception as e:
        # Unexpected error in code
        exc_type, exc_obj, exc_tb = sys.exc_info()
        fname = os.path.split(exc_tb.tb_frame.f_code.co_filename)[1]
        ex_str = str(e) + " at " + str(exc_type) + ": " + \
            fname + ": line " + str(exc_tb.tb_lineno)
        print(ex_str)

        return jsonify({
            "code": 500,
            "message": "place_order.py internal error: " + ex_str
        }), 500


# ======================== HELPER FUNCTION (START) ========================
def processOrder(products):
    payment_result = invoke_http(payment_URL, method='POST', json=products)

    # print("TEST payment_result (START)")
    # print(payment_result)
    # print("TEST payment_result (END)")

    # ========================= AMQP (START) =========================
    code = payment_result["code"]
    message = json.dumps(payment_result)
    # print("TEST code (START)")
    # print(code)
    # print("TEST code (END)")
    ###################################
    # print("TEST message (START)")
    # print(message)
    # print("TEST message (END)")
    amqp_setup.check_setup()

    if code not in range(200, 300):
        amqp_setup.channel.basic_publish(exchange=amqp_setup.exchangename, routing_key="order.error",
                                         body=message, properties=pika.BasicProperties(delivery_mode=2))

        print("\nOrder status ({:d}) published to the RabbitMQ Exchange:".format(
            code), payment_result)

        return {
            "code": 500,
            "data": {"payment_result": payment_result},
            "message": payment_result['message']
        }

    else:
        amqp_setup.channel.basic_publish(exchange=amqp_setup.exchangename, routing_key="order.info",
                                         body=message)
    # ========================= AMQP (END) =========================

    # Return created Order
    return {
        "code": 201,
        "data": {
            "payment_result": payment_result
        },
        "message": "Payment Successful! Thank you for shopping with us :)"
    }
# ======================== HELPER FUNCTION (END) ========================


@app.route('/add_to_cart', methods=['POST'])
def add_to_cart():

    data = request.get_json()
    print(data)
    userId = data["userId"]
    productID = data["productID"]
    qtyInput = data["qtyInput"]
    print("printing product")
    print(productID)

    # use axios to make a post request to listingMS
    # listingMS will return the product with the productID
    result = invoke_http(listing_URL + "/products/" +
                         str(productID), method='GET')
    product = result["data"]["product"]

    # check if the quantity is available
    # if not, return error message
    if (product["quantity"] < int(qtyInput)):
        print("qty less that inventory")

        return jsonify({
            'code': 400,
            "message": "Enter valid quantity!"
        }), 400

    # if yes, invoke cartMS to add to cart
    # cartMS will return the cart
    data = {
        "userId": userId,
        "productID": productID,
        "qtyInput": qtyInput,
        "product": product
    }
    # try:
    cart = invoke_http(cart_URL + "/add_to_cart", method='POST', json=data)

    if (cart["code"] == 200):

        return jsonify({
            'code': 200,
            "message": "Item added to cart!"
        }), 200

    else:
        return jsonify({
            'code': 400,
            "message": "Item already in cart!"
        }), 400


# display user cart on UI
@app.route('/get_cart/<userId>', methods=['GET'])
def get_cart(userId):

    try:
        data = {
            "buyerID": userId
        }
        # invoke cartMS to get the cart
        result = invoke_http(cart_URL + "/get_cart", method='GET', json=data)

        cart_list = result["data"]["cart_list"]

        return jsonify({
            'code': 200,
            'message': 'Cart retrieved successfully',
            'data': {
                'cart_list': cart_list
            }
        })

    except:
        return jsonify({
            'code': 400,
            'message': 'Unable to retrieve all cart items'
        }), 400

# # adding to order function
# @app.route('/add_to_orders', methods = ['POST'])


def add_to_orders():
    paymentResult, paymentStatus, buyerID = buy_item()

    if paymentStatus == 200:
        getAllItemsURL = cart_URL + "/get_cart"
        cartResult = invoke_http(getAllItemsURL, method='GET', json=buyerID)
        allCartItems = cartResult["data"]["cart_list"]
        buyerID = allCartItems[0]["buyerID"]

        addingOrderURL = order_URL + "/add_order/" + str(buyerID)
        addingOrderResult = invoke_http(
            addingOrderURL, method='POST', json=allCartItems)

        return jsonify(
            {
                "code": 200,
                "message": "Order added successfully",
                "data": {
                    "cart_list": allCartItems
                }
            }
        ), 200

    else:
        return jsonify(
            {
                "code": 400,
                "message": "Order was not added successfully"
            }
        ), 400


# # updating the listings automatically upon adding to orders
# @app.route('/update_listing', methods = ['PUT'])
def update_listing():
    result = add_to_orders()
    addOrdersStatus = result["code"]
    allCartItems = result["data"]["cart-list"]

    if addOrdersStatus == 200:
        for item in allCartItems:
            productID = item["productID"]
            soldQuantity = item["inputQuantity"]
            updateListingURL = listing_URL + "/update_sold_product_qty"
            updateListingPayload = {
                "productID": productID, "soldQuantity": soldQuantity}
            updateListingResult = invoke_http(
                updateListingURL, method="PUT", json=updateListingPayload)

            if updateListingResult["Code"] == 200:
                updatedItem = updateListingResult["data"]["product"]
                if updatedItem["quantity"] <= 0:
                    deleteListingURL = listing_URL + \
                        "/remove_product/" + str(productID)
                    deleteListingResult = invoke_http(
                        deleteListingURL, method="DELETE")

        return jsonify(
            {
                "code": 200,
                "message": "Order added successfully",
                "data": {
                    "cart_list": allCartItems
                }
            }
        ), 200

    else:
        return jsonify(
            {
                "code": 400,
                "message": "Order was not added successfully"
            }
        ), 400

# # delete from cart once listings have been updated
# @app.route('/delete_from_cart', methods = ['DELETE'])


def delete_from_cart():
    result = update_listing()
    updateListingStatus = result["code"]
    allCartItems = result["data"]["cart-list"]

    if updateListingStatus == 200:
        buyerID = allCartItems[0]["buyerID"]
        deleteFromCartURL = cart_URL + "/delete_from_cart/" + buyerID
        deleteFromCartResult = invoke_http(deleteFromCartURL, method="DELETE")

        return jsonify(
            {
                "code": 200,
                "message": "Order added successfully",
                "data": {
                    "cart_list": allCartItems
                }
            }
        ), 200

    else:
        return jsonify(
            {
                "code": 400,
                "message": "Order was not added successfully"
            }
        ), 400

# deleting 1 item from cart on UI


@app.route('/delete_cart_item/<userId>/<int:productID>', methods=['DELETE'])
def delete_cart_item(userId, productID):

    try:
        result = invoke_http(cart_URL + "/delete_one_item/" +
                             userId + "/" + str(productID), method='DELETE')

        return jsonify({
            'code': 200,
            'message': 'Item deleted successfully'
        })

    except:
        return jsonify({
            'code': 405,
            'message': 'Unable to delete item'
        }), 405


if __name__ == '__main__':
    app.run(port=5200, debug=True)
