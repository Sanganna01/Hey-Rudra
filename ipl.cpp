#include <iostream>
#include <vector>
#include <algorithm>

std::vector<int> twoSum(std::vector<int>& nums, int target) {
    std::vector<int> result;
    for (int i = 0; i < nums.size(); i++) {
        for (int j = i + 1; j < nums.size(); j++) {
            if (nums[i] + nums[j] == target) {
                result.push_back(i);
                result.push_back(j);
                return result;
            }
        }
    }
    return result;
}

int main() {
    std::vector<int> nums = {2, 7, 11, 15};
    int target = 9;
    std::vector<int> result = twoSum(nums, target);
    std::cout << "Indices: " << result[0] << ", " << result[1] << std::endl;
    return 0;
}