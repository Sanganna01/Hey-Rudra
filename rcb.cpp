#include <iostream>
#include <vector>
#include <string>

class Product {
public:
    std::string name;
    double price;

    Product(std::string name, double price) : name(name), price(price) {}
};

class ShoppingCart {
private:
    std::vector<Product> products;

public:
    void addProduct(const Product& product) {
        products.push_back(product);
    }

    void removeProduct(const std::string& productName) {
        for (auto it = products.begin(); it != products.end(); ++it) {
            if (it->name == productName) {
                products.erase(it);
                return;
            }
        }
    }

    double calculateTotal() const {
        double total = 0.0;
        for (const auto& product : products) {
            total += product.price;
        }
        return total;
    }

    void displayProducts() const {
        for (const auto& product : products) {
            std::cout << "Product: " << product.name << ", Price: " << product.price << std::endl;
        }
    }
};

int main() {
    ShoppingCart cart;

    Product product1("Apple", 1.99);
    Product product2("Banana", 0.99);
    Product product3("Orange", 2.49);

    cart.addProduct(product1);
    cart.addProduct(product2);
    cart.addProduct(product3);

    std::cout << "Shopping Cart Contents:" << std::endl;
    cart.displayProducts();

    std::cout << "Total: " << cart.calculateTotal() << std::endl;

    cart.removeProduct("Banana");

    std::cout << "Shopping Cart Contents after removal:" << std::endl;
    cart.displayProducts();

    std::cout << "Total after removal: " << cart.calculateTotal() << std::endl;

    return 0;
}