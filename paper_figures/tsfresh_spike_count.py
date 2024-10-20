import logging
import sys
import warnings
from dataclasses import asdict

import chika
import pandas as pd
from imblearn.metrics import geometric_mean_score
from sklearn.ensemble import ExtraTreesClassifier, RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import cohen_kappa_score, roc_auc_score
from spikebench import load_allen, load_fcx1, load_temporal, load_retina, load_epirest
from spikebench.helpers import (set_random_seed, subsampled_fit_predict,
                                tsfresh_vectorize_spike_count)
from xgboost import XGBClassifier

DATASET_NAME_LOADER_MAP = {
    'fcx1': load_fcx1,
    'retina': load_retina,
    'allen': load_allen,
    'fcx1_temporal': load_temporal,
    'epirest': load_epirest,
}


model_zoo = {
        'random_forest': RandomForestClassifier(
            n_estimators=500,
            random_state=0,
            max_depth=10,
            n_jobs=-1
        ),
        'extra_trees': ExtraTreesClassifier(
            n_estimators=500,
            random_state=0,
            max_depth=None,
            n_jobs=-1
        ),
        'logit_l2': LogisticRegression(
            random_state=0,
            penalty='l2',
            C=1e-3,
            n_jobs=-1,
        ),
        'logit_elastic': LogisticRegression(
            random_state=0,
            penalty='elasticnet',
            solver='saga',
            l1_ratio=0.5
        ),
        'xgboost': XGBClassifier(
            max_depth=8,
            learning_rate=1e-1,
            n_estimators=500,
            verbosity=0,
            silent=None,
            objective='binary:logistic',
            booster='gbtree',
            n_jobs=-1,
            nthread=None,
            gamma=0,
            min_child_weight=1,
            max_delta_step=0,
            subsample=0.7,
            colsample_bytree=1,
            colsample_bylevel=1,
            colsample_bynode=1,
            reg_alpha=0,
            reg_lambda=1,
            scale_pos_weight=1,
            base_score=0.5,
            random_state=0,
            seed=0
        )
}


@chika.config
class Config:
    seed: int = 0
    dataset: str = 'epirest'
    balanced: bool = False
    preprocessing: bool = True
    train_subsample_factor: float = 0.7
    test_subsample_factor: float = 0.7
    trials: int = 5
    tsfresh_feature_set: str = None
    tsfresh_remove_low_variance: bool = True
    tsfresh_scale_features: bool = True
    bin_size: int = 200
    out_folder: str = 'csv'


@chika.main(cfg_cls=Config)
def main(cfg: Config):
    set_random_seed(cfg.seed)

    logging.info(
        f'Running job with config {asdict(cfg)}'
    )

    feature_sets = ('full', )
    for feature_set in feature_sets:
        cfg.tsfresh_feature_set = feature_set

        loader_fn = DATASET_NAME_LOADER_MAP[cfg.dataset]
        X_train, X_test, y_train, y_test, gr_train, gr_test = loader_fn(random_seed=cfg.seed,
            encoding='sce', bin_size=cfg.bin_size)

        X_train, X_test, y_train, y_test = tsfresh_vectorize_spike_count(X_train, X_test, y_train, y_test, cfg,
                cache_file=f'./bin/tsfresh_features_{cfg.dataset}_{cfg.tsfresh_feature_set}_sce.bin')

        logging.info(
            f'Dataset shape after preprocessing: train {X_train.shape}, test {X_test.shape}'
        )
        logging.info(
            f'Mean target values: train {y_train.mean()}, test {y_test.mean()}'
        )

        models = {f'tsfresh_{feature_set}_{model_name}_sce': model for model_name, model in model_zoo.items()}

        if cfg.balanced:
            results = subsampled_fit_predict(models, X_train, X_test, y_train, y_test, cfg)
            results.to_csv(f'{cfg.out_folder}/{cfg.dataset}_{feature_set}_sce_tsfresh_balanced.csv', index=False)
        else:
            results = {'model_name': [], 'roc_auc': [], 'gmean': [], 'cohen_kappa': []}
            for model_name, model in models.items():

                logging.info(f'Fitting model {model_name}')
                model.fit(X_train, y_train)
                test_preds = model.predict(X_test)
                test_probas = model.predict_proba(X_test)[:, 1]

                results['model_name'].append(model_name)
                results['roc_auc'].append(roc_auc_score(y_test, test_probas))
                results['gmean'].append(geometric_mean_score(y_test, test_preds))
                results['cohen_kappa'].append(cohen_kappa_score(y_test, test_preds))

                res_table = pd.DataFrame(results)
                logging.info(f'Validation metrics\n{res_table}')
                res_table.to_csv(f'{cfg.out_folder}/{cfg.dataset}_{feature_set}_sce_tsfresh_imbalanced.csv', index=False)


if __name__ == '__main__':
    warnings.filterwarnings('ignore')
    logging.basicConfig(level=logging.INFO, stream=sys.stdout)
    main()
