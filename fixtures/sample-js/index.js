const { charge } = require("./billing");
const { Authenticator, hashPassword } = require("./auth");

function createOrder(username, password, amount) {
  const auth = new Authenticator({ alice: hashPassword("hunter2") });
  return charge(auth, username, password, amount);
}

module.exports = { createOrder };
