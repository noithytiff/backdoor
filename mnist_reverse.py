#!/usr/bin/env python
# -*- coding: utf-8 -*-
# @Date    : 2018-11-05 11:30:01
# @Author  : Bolun Wang (bolunwang@cs.ucsb.edu)
# @Link    : http://cs.ucsb.edu/~bolunwang

import os
import time

import numpy as np
import random
from tensorflow import set_random_seed
random.seed(123)
np.random.seed(123)
set_random_seed(123)

import keras
from keras.models import load_model
from keras.preprocessing.image import ImageDataGenerator

from visualizer import Visualizer

import utils_backdoor
import h5py

##############################
#        PARAMETERS          #
##############################

DEVICE = '2'  # specify which GPU to use

DATA_DIR = 'data'  # data folder
DATA_FILE = 'test.hdf5'  # dataset file
MODEL_DIR = 'models'  # model directory
MODEL_FILENAME = 'kmnist.h5'  # model file
RESULT_DIR = 'results'  # directory for storing results
# image filename template for visualization results
IMG_FILENAME_TEMPLATE = 'mnist_visualize_%s_label_%d.png'
CHANNELS_FIRST = True

# input size
IMG_ROWS = 28
IMG_COLS = 28
IMG_COLOR = 1
if CHANNELS_FIRST:
    INPUT_SHAPE = (IMG_COLOR, IMG_ROWS, IMG_COLS)
else:
    INPUT_SHAPE = (IMG_ROWS, IMG_COLS, IMG_COLOR)

NUM_CLASSES = 10  # total number of classes in the model
# (optional) infected target label, used for prioritizing label scanning
Y_TARGET = 2

# preprocessing method for the task, GTSRB uses raw pixel intensities
INTENSITY_RANGE = 'mnist'

# parameters for optimization
BATCH_SIZE = 32  # batch size used for optimization
LR = 0.1  # learning rate
STEPS = 1000  # total optimization iterations
NB_SAMPLE = 1000  # number of samples in each mini batch
MINI_BATCH = NB_SAMPLE // BATCH_SIZE  # mini batch size used for early stop
INIT_COST = 1e-3  # initial weight used for balancing two objectives

REGULARIZATION = 'l1'  # reg term to control the mask's norm

ATTACK_SUCC_THRESHOLD = 0.99  # attack success threshold of the reversed attack
PATIENCE = 5  # patience for adjusting weight, number of mini batches
COST_MULTIPLIER = 2  # multiplier for auto-control of weight (COST)
SAVE_LAST = False  # whether to save the last result or best result

EARLY_STOP = True  # whether to early stop
EARLY_STOP_THRESHOLD = 1.0  # loss threshold for early stop
EARLY_STOP_PATIENCE = 5 * PATIENCE  # patience for early stop

# the following part is not used in our experiment
# but our code implementation also supports super-pixel mask
UPSAMPLE_SIZE = 1  # size of the super pixel
if CHANNELS_FIRST:
    MASK_SHAPE = np.ceil(
        np.array(INPUT_SHAPE[1:], dtype=float) / UPSAMPLE_SIZE)
else:
    MASK_SHAPE = np.ceil(
        np.array(INPUT_SHAPE[0:2], dtype=float) / UPSAMPLE_SIZE)
MASK_SHAPE = MASK_SHAPE.astype(int)

# parameters of the original injected trigger
# this is NOT used during optimization
# start inclusive, end exclusive
# PATTERN_START_ROW, PATTERN_END_ROW = 27, 31
# PATTERN_START_COL, PATTERN_END_COL = 27, 31
# PATTERN_COLOR = (255.0, 255.0, 255.0)
# PATTERN_LIST = [
#     (row_idx, col_idx, PATTERN_COLOR)
#     for row_idx in range(PATTERN_START_ROW, PATTERN_END_ROW)
#     for col_idx in range(PATTERN_START_COL, PATTERN_END_COL)
# ]

##############################
#      END PARAMETERS        #
##############################

if CHANNELS_FIRST:
    keras.backend.set_image_data_format('channels_first')


def load_dataset(data_file=('%s/%s' % (DATA_DIR, DATA_FILE))):

    dataset = utils_backdoor.load_dataset(data_file, keys=['X_test', 'Y_test'])

    X_test = np.array(dataset['X_test'], dtype='float32')
    Y_test = np.array(dataset['Y_test'], dtype='float32')

    if CHANNELS_FIRST:
        # X_test = np.moveaxis(X_test, -1, 1)
        X_test = np.rollaxis(X_test, 3, 1)
    print('X_test shape %s' % str(X_test.shape))
    print('Y_test shape %s' % str(Y_test.shape))

    return X_test, Y_test


def build_data_loader(X, Y):

    datagen = ImageDataGenerator()
    generator = datagen.flow(
        X, Y, batch_size=BATCH_SIZE)

    return generator


def visualize_trigger_w_mask(visualizer, gen, y_target,
                             save_pattern_flag=True):

    visualize_start_time = time.time()

    # initialize with random mask
    pattern = np.random.random(INPUT_SHAPE) * 255.0
    mask = np.random.random(MASK_SHAPE)

    # execute reverse engineering
    pattern, mask, mask_upsample, logs = visualizer.visualize(
        gen=gen, y_target=y_target, pattern_init=pattern, mask_init=mask)

    # meta data about the generated mask
    print('pattern, shape: %s, min: %f, max: %f' %
          (str(pattern.shape), np.min(pattern), np.max(pattern)))
    print('mask, shape: %s, min: %f, max: %f' %
          (str(mask.shape), np.min(mask), np.max(mask)))
    print('mask norm of label %d: %f' %
          (y_target, np.sum(np.abs(mask_upsample))))

    visualize_end_time = time.time()
    print('visualization cost %f seconds' %
          (visualize_end_time - visualize_start_time))

    if save_pattern_flag:
        save_pattern(pattern, mask_upsample, y_target)

    return pattern, mask_upsample, logs


def save_pattern(pattern, mask, y_target):

    # create result dir
    if not os.path.exists(RESULT_DIR):
        os.mkdir(RESULT_DIR)

    img_filename = (
        '%s/%s' % (RESULT_DIR,
                   IMG_FILENAME_TEMPLATE % ('pattern', y_target)))
    utils_backdoor.dump_image(pattern, img_filename, 'png')

    img_filename = (
        '%s/%s' % (RESULT_DIR,
                   IMG_FILENAME_TEMPLATE % ('mask', y_target)))
    if CHANNELS_FIRST:
        utils_backdoor.dump_image(np.expand_dims(mask, axis=0) * 255,
                                  img_filename,
                                  'png')

    else:
        utils_backdoor.dump_image(np.expand_dims(mask, axis=2) * 255,
                                  img_filename,
                                  'png')

    if CHANNELS_FIRST:
        fusion = np.multiply(pattern, np.expand_dims(mask, axis=0))
    else:
        fusion = np.multiply(pattern, np.expand_dims(mask, axis=2))
    img_filename = (
        '%s/%s' % (RESULT_DIR,
                   IMG_FILENAME_TEMPLATE % ('fusion', y_target)))
    utils_backdoor.dump_image(fusion, img_filename, 'png')

    pass


def gtsrb_visualize_label_scan_bottom_right_white_4():

    print('loading dataset')
    filename = "./data/test.hdf5"

    with h5py.File(filename, "r") as f:
        # List all groups
        print("Keys: %s" % f.keys())
        c_group_key = list(f.keys())[0]
        d_group_key = list(f.keys())[1]

        # Get the data
        X_test = list(f[c_group_key])
        Y_test = list(f[d_group_key])
    X_test = np.array(np.array(X_test).flatten()).reshape(10000, 28, 28, 1)
    X_test = np.transpose(X_test,(0,3,1,2))
    y_test = np.eye(10)[np.array(Y_test).reshape(-1)]

    # Assume inputs are preprocessed.
    X_test = X_test / 255.

    print('X_test shape %s' % str(X_test.shape))
    print('Y_test shape %s' % str(y_test.shape))
    print('X_test min', np.min(X_test))
    print('X_test max', np.max(X_test))
    # transform numpy arrays into data generator
    test_generator = build_data_loader(X_test, Y_test)

    print('loading model')
    model_file = '%s/%s' % (MODEL_DIR, MODEL_FILENAME)
    model = load_model(model_file)

    print(model.summary())

    # initialize visualizer
    visualizer = Visualizer(
        model, intensity_range=INTENSITY_RANGE, regularization=REGULARIZATION,
        input_shape=INPUT_SHAPE, channels_first=CHANNELS_FIRST,
        init_cost=INIT_COST, steps=STEPS, lr=LR, num_classes=NUM_CLASSES,
        mini_batch=MINI_BATCH,
        upsample_size=UPSAMPLE_SIZE,
        attack_succ_threshold=ATTACK_SUCC_THRESHOLD,
        patience=PATIENCE, cost_multiplier=COST_MULTIPLIER,
        img_color=IMG_COLOR, batch_size=BATCH_SIZE, verbose=2,
        save_last=SAVE_LAST,
        early_stop=EARLY_STOP, early_stop_threshold=EARLY_STOP_THRESHOLD,
        early_stop_patience=EARLY_STOP_PATIENCE)

    log_mapping = {}

    # y_label list to analyze
    y_target_list = list(range(NUM_CLASSES))
    y_target_list.remove(Y_TARGET)
    y_target_list = [Y_TARGET] + y_target_list
    for y_target in y_target_list:

        print('processing label %d' % y_target)

        _, _, logs = visualize_trigger_w_mask(
            visualizer, test_generator, y_target=y_target,
            save_pattern_flag=True)

        log_mapping[y_target] = logs

    pass


def main():
    os.environ["CUDA_VISIBLE_DEVICES"] = DEVICE
    utils_backdoor.fix_gpu_memory()
    gtsrb_visualize_label_scan_bottom_right_white_4()

    pass


if __name__ == '__main__':

    start_time = time.time()
    main()
    elapsed_time = time.time() - start_time
    print('elapsed time %s s' % elapsed_time)
